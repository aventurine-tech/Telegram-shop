import asyncio
import datetime
import fnmatch
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool


class FakeCacheManager:
    """Dict-based cache that mirrors CacheManager's interface."""

    def __init__(self):
        self.store: Dict[str, Any] = {}
        self.hits = 0
        self.misses = 0

    async def get(self, key: str, deserialize: bool = True):
        if key in self.store:
            self.hits += 1
            return self.store[key]
        self.misses += 1
        return None

    async def set(self, key: str, value, ttl: int = None, serialize: bool = True):
        self.store[key] = value
        return True

    async def delete(self, key: str):
        self.store.pop(key, None)
        return True

    async def delete_many(self, keys):
        for key in keys:
            self.store.pop(key, None)
        return True

    async def invalidate_pattern(self, pattern: str):
        to_delete = [k for k in self.store if fnmatch.fnmatch(k, pattern)]
        for k in to_delete:
            del self.store[k]
        return len(to_delete)

    async def check_health(self):
        return True

    def clear(self):
        self.store.clear()
        self.hits = 0
        self.misses = 0


class FakeFSMContext:
    """Dict-backed FSMContext replacement."""

    def __init__(self):
        self._state = None
        self._data: Dict[str, Any] = {}

    async def set_state(self, state=None):
        self._state = state

    async def get_state(self):
        return self._state

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def get_data(self):
        return self._data.copy()

    async def clear(self):
        self._state = None
        self._data = {}


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Replace Database singleton with async SQLite in-memory engine for all tests."""
    from bot.database.main import Database

    # Reset singleton
    Database.reset_instance()

    # Save original init
    original_init = Database.__init__

    def test_init(self):
        self.__dict__['_Database__engine'] = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.__dict__['_Database__SessionLocal'] = async_sessionmaker(
            bind=self.__dict__['_Database__engine'],
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    Database.__init__ = test_init

    # Create all tables synchronously using the async engine
    db = Database()

    async def _setup():
        async with db.engine.begin() as conn:
            await conn.run_sync(Database.BASE.metadata.create_all)
        from bot.database.models.main import Role
        await Role.insert_roles()

    asyncio.run(_setup())

    yield

    Database.__init__ = original_init
    Database.reset_instance()


@pytest.fixture(autouse=True)
async def db_cleanup(setup_test_database):
    """
    Clean all data between tests by deleting rows from all tables
    (except roles which are session-scoped).
    """
    yield

    from bot.database.main import Database
    from bot.database.models.main import (
        ReferralEarnings, Operations, OrderItems, Orders,
        Goods, Categories, User, Role,
        Reviews, CartItems, PromoCodeUsages, PromoCodes,
        StockSubscriptions, ProductImages, WebUsers, Favorites,
    )

    db = Database()
    async with db.session() as s:
        # Delete in FK order.
        await s.execute(delete(Reviews))
        await s.execute(delete(StockSubscriptions))
        await s.execute(delete(Favorites))
        await s.execute(delete(CartItems))
        await s.execute(delete(PromoCodeUsages))
        await s.execute(delete(PromoCodes))
        await s.execute(delete(ReferralEarnings))
        await s.execute(delete(OrderItems))
        await s.execute(delete(Orders))
        await s.execute(delete(Operations))
        await s.execute(delete(ProductImages))
        await s.execute(delete(Goods))
        await s.execute(delete(Categories))
        await s.execute(delete(User))
        await s.execute(delete(WebUsers))
        # Delete custom roles (keep built-in)
        await s.execute(delete(Role).where(Role.name.notin_(['USER', 'ADMIN', 'OWNER'])))


@pytest.fixture(autouse=True)
def fake_cache():
    """Provide a FakeCacheManager and patch get_cache_manager everywhere."""
    cache = FakeCacheManager()

    with patch('bot.misc.caching.cache._cache_manager', cache), \
            patch('bot.misc.caching.cache.get_cache_manager', return_value=cache), \
            patch('bot.database.methods.read.get_cache_manager', return_value=cache):
        yield cache


@pytest.fixture(autouse=True)
def patch_safe_create_task():
    """Make safe_create_task execute coroutines immediately."""

    def run_immediately(coro):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)

    with patch('bot.database.methods.cache_utils.safe_create_task', side_effect=run_immediately), \
            patch('bot.database.methods.create.safe_create_task', side_effect=run_immediately), \
            patch('bot.database.methods.update.safe_create_task', side_effect=run_immediately), \
            patch('bot.database.methods.delete.safe_create_task', side_effect=run_immediately), \
            patch('bot.database.methods.transactions.safe_create_task', side_effect=run_immediately), \
            patch('bot.database.methods.orders.safe_create_task', side_effect=run_immediately), \
            patch('bot.database.methods.product_images.safe_create_task', side_effect=run_immediately):
        yield


@pytest.fixture(autouse=True)
def patch_env_keys():
    """Provide safe default EnvKeys for tests."""
    patches = {
        'PAY_CURRENCY': 'MDL',
        'REFERRAL_PERCENT': 10,
        'OWNER_ID': 999999,
        'MIN_AMOUNT': 10,
        'MAX_AMOUNT': 10000,
        'MIA_RECIPIENT': 'Test Shop SRL',
        'MIA_PHONE': '+37360000000',
        'MIA_IBAN': 'MD00TEST000000000000',
        'MIA_PAY_TIMEOUT_MIN': 120,
        'COD_ENABLED': '1',
        'DELIVERY_ENABLED': '1',
        'PICKUP_ENABLED': '1',
        'PICKUP_ADDRESS': 'Test street 1',
        'DELIVERY_INFO': '',
        'ORDERS_CHAT_ID': '',
        'CHANNEL_URL': '',
        'HELPER_ID': '',
        'RULES': 'Test rules',
    }

    with patch.multiple('bot.misc.env.EnvKeys', **patches):
        yield


# Every module that does `from bot.i18n import localize`. Patched when importable, so a
# module that is renamed or removed doesn't break the whole suite.
_LOCALIZING_MODULES = (
    'bot.handlers.user.main',
    'bot.handlers.user.shop_and_goods',
    'bot.handlers.user.referral_system',
    'bot.handlers.user.cart',
    'bot.handlers.user.checkout',
    'bot.handlers.user.balance_and_payment',
    'bot.handlers.user.language',
    'bot.handlers.user.bottom_nav',
    'bot.keyboards.reply',
    'bot.handlers.admin.user_management',
    'bot.handlers.admin.categories_management',
    'bot.handlers.admin.goods_management',
    'bot.handlers.admin.adding_position',
    'bot.handlers.admin.translations',
    'bot.keyboards.translations',
    'bot.handlers.admin._common',
    'bot.handlers.admin.sale_management',
    'bot.handlers.admin.role_management',
    'bot.handlers.admin.orders_management',
    'bot.misc.services.order_view',
)


@pytest.fixture(autouse=True)
def mock_localize():
    """localize() returns the key so tests can assert which message was sent."""
    import contextlib
    import importlib

    def fake_localize(key, **kwargs):
        if kwargs:
            return f"{key}:{kwargs}"
        return key

    with contextlib.ExitStack() as stack:
        m = stack.enter_context(patch('bot.i18n.localize', side_effect=fake_localize))
        for path in _LOCALIZING_MODULES:
            try:
                module = importlib.import_module(path)
            except Exception:  # missing, renamed, or mid-refactor: nothing to patch
                continue
            if hasattr(module, 'localize'):
                stack.enter_context(patch.object(module, 'localize', side_effect=fake_localize))
        yield m


@pytest.fixture
def user_factory():
    """Factory to create test users."""
    from sqlalchemy import update as sa_update
    from bot.database.main import Database
    from bot.database.models.main import User
    from bot.database.methods.create import create_user
    from bot.database.methods.read import check_user

    async def _create(
            telegram_id: int = 100001,
            balance: int = 0,
            role_id: int = 1,
            referral_id: int = None,
            language: str = None,
    ):
        await create_user(
            telegram_id=telegram_id,
            registration_date=datetime.datetime.now(datetime.timezone.utc),
            referral_id=referral_id,
            role=role_id,
        )
        if balance > 0:
            async with Database().session() as s:
                await s.execute(
                    sa_update(User).where(User.telegram_id == telegram_id).values(balance=balance)
                )
        if language:
            from bot.database.methods.update import set_user_language
            await set_user_language(telegram_id, language)
        return await check_user(telegram_id)

    return _create


@pytest.fixture
def operation_factory():
    """Seed a balance Operations row (see tests/factories.py)."""
    from tests.factories import add_operation
    return add_operation


@pytest.fixture
def referral_earning_factory():
    """Seed a ReferralEarnings row (see tests/factories.py)."""
    from tests.factories import add_referral_earning
    return add_referral_earning


@pytest.fixture
def category_factory():
    """Factory to create categories."""
    from bot.database.methods.create import create_category

    async def _create(name: str = "TestCategory"):
        await create_category(name)

    return _create


@pytest.fixture
def item_factory(category_factory):
    """Factory to create items with an optional units-on-hand count."""
    from bot.database.methods.create import create_item

    async def _create(
            name: str = "TestItem",
            price: int = 100,
            category: str = "TestCategory",
            description: str = "Test description",
            stock: int = 0,
    ):
        await category_factory(category)
        await create_item(name, description, price, category, stock=stock)

    return _create


@pytest.fixture
def mock_bot():
    """Mock bot with common method signatures."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.get_chat = AsyncMock(return_value=MagicMock(first_name="TestUser"))
    bot.get_chat_member = AsyncMock()
    return bot


@pytest.fixture
def make_callback_query(mock_bot):
    """Factory to create CallbackQuery mocks."""

    def _make(data: str = "test", user_id: int = 100001, first_name: str = "TestUser"):
        call = AsyncMock()
        call.data = data
        call.from_user = MagicMock()
        call.from_user.id = user_id
        call.from_user.first_name = first_name
        call.from_user.is_bot = False
        call.message = AsyncMock()
        call.message.bot = mock_bot
        call.message.edit_text = AsyncMock()
        call.message.date = MagicMock()
        call.message.date.timestamp = MagicMock(return_value=datetime.datetime.now().timestamp())
        call.bot = mock_bot
        call.answer = AsyncMock()
        return call

    return _make


@pytest.fixture
def make_message(mock_bot):
    """Factory to create Message mocks."""

    def _make(text: str = "/start", user_id: int = 100001, first_name: str = "TestUser"):
        msg = AsyncMock()
        msg.text = text
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
        msg.from_user.first_name = first_name
        msg.from_user.is_bot = False
        msg.chat = MagicMock()
        msg.chat.type = "private"
        msg.bot = mock_bot
        msg.answer = AsyncMock()
        msg.delete = AsyncMock()
        return msg

    return _make


@pytest.fixture
def fsm_context():
    """Provide a FakeFSMContext instance."""
    return FakeFSMContext()


@pytest.fixture
def role_factory():
    """Factory to create custom roles."""
    from bot.database.methods.create import create_role

    async def _create(name: str = "CUSTOM", permissions: int = 3):
        return await create_role(name, permissions)

    return _create


@pytest.fixture
def english():
    """Render web-panel text in English (the default language of the test environment is Russian)."""
    from bot.i18n.main import use_language
    with use_language("en"):
        yield
