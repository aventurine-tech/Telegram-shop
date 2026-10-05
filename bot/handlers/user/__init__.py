from .main import router as main_router
from .checkout import router as checkout_router
from .shop_and_goods import router as shop_and_goods_router
from .referral_system import router as referral_system_router
from .cart import router as cart_router

from aiogram import Router

router = Router()
router.include_router(main_router)
router.include_router(checkout_router)
router.include_router(shop_and_goods_router)
router.include_router(referral_system_router)
router.include_router(cart_router)
