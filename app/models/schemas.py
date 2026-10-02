from typing import List, Optional, Any, Dict, Union
from pydantic import BaseModel, Field

# ========================================================
# 1. Product Schemas
# ========================================================
class ProductBase(BaseModel):
    name: str
    price: float
    oldPrice: Optional[float] = None
    category: str
    rating: Optional[float] = 5.0
    reviews: Optional[int] = 0
    img: Optional[str] = "product_flower_necklace.jpg"
    badges: Optional[List[str]] = Field(default_factory=list)
    inStock: Optional[bool] = True
    sku: Optional[str] = None
    material: Optional[str] = None
    dimensions: Optional[str] = None
    description: Optional[str] = None
    variants: Optional[List[str]] = Field(default_factory=list)
    images: Optional[List[str]] = Field(default_factory=list)

class ProductCreate(ProductBase):
    id: Optional[int] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    oldPrice: Optional[float] = None
    category: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None
    img: Optional[str] = None
    badges: Optional[List[str]] = None
    inStock: Optional[bool] = None
    sku: Optional[str] = None
    material: Optional[str] = None
    dimensions: Optional[str] = None
    description: Optional[str] = None
    variants: Optional[List[str]] = None
    images: Optional[List[str]] = None

class ProductStockUpdate(BaseModel):
    inStock: bool

class ProductOut(ProductBase):
    id: int

# ========================================================
# 2. Category Schemas
# ========================================================
class CategoryBase(BaseModel):
    name: str
    count: Optional[int] = 0
    img: Optional[str] = None
    desc: Optional[str] = None

class CategoryCreate(CategoryBase):
    id: str

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    count: Optional[int] = None
    img: Optional[str] = None
    desc: Optional[str] = None

class CategoryOut(CategoryBase):
    id: str

# ========================================================
# 3. Review Schemas
# ========================================================
class ReviewBase(BaseModel):
    name: str
    rating: int = 5
    text: str
    date: Optional[str] = None
    verified: Optional[bool] = True
    approved: Optional[bool] = True
    product: Optional[str] = "General"

class ReviewCreate(ReviewBase):
    id: Optional[int] = None

class ReviewUpdate(BaseModel):
    name: Optional[str] = None
    rating: Optional[int] = None
    text: Optional[str] = None
    date: Optional[str] = None
    verified: Optional[bool] = None
    approved: Optional[bool] = None
    product: Optional[str] = None

class ReviewStatusUpdate(BaseModel):
    approved: bool

class ReviewOut(ReviewBase):
    id: int

# ========================================================
# 4. Offers & Combos Schemas
# ========================================================
class CouponBase(BaseModel):
    code: str
    title: str
    discount: float
    type: str = "percent"  # 'percent', 'fixed', 'free_shipping'
    minOrder: Optional[float] = 0
    expiry: Optional[str] = "2026-12-31"
    desc: Optional[str] = None
    badge: Optional[str] = None
    active: Optional[bool] = True

class CouponCreate(CouponBase):
    id: Optional[str] = None

class CouponUpdate(BaseModel):
    code: Optional[str] = None
    title: Optional[str] = None
    discount: Optional[float] = None
    type: Optional[str] = None
    minOrder: Optional[float] = None
    expiry: Optional[str] = None
    desc: Optional[str] = None
    badge: Optional[str] = None
    active: Optional[bool] = None

class CouponOut(CouponBase):
    id: str

class ComboBase(BaseModel):
    name: str
    discount: str
    price: float
    oldPrice: float
    items: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)

class ComboCreate(ComboBase):
    id: Optional[str] = None

class ComboUpdate(BaseModel):
    name: Optional[str] = None
    discount: Optional[str] = None
    price: Optional[float] = None
    oldPrice: Optional[float] = None
    items: Optional[List[str]] = None
    images: Optional[List[str]] = None

class ComboOut(ComboBase):
    id: str

class OffersOut(BaseModel):
    coupons: List[CouponOut]
    combos: List[ComboOut]

class ValidateCouponRequest(BaseModel):
    code: str
    orderTotal: float

class ValidateCouponResponse(BaseModel):
    valid: bool
    message: str
    discountAmount: float = 0.0
    discountType: Optional[str] = None
    freeShipping: bool = False
    coupon: Optional[CouponOut] = None

# ========================================================
# 5. Order Schemas
# ========================================================
class OrderItem(BaseModel):
    id: Union[int, str]
    name: str
    price: float
    qty: int = 1
    variant: Optional[str] = None
    img: Optional[str] = None

class OrderCreate(BaseModel):
    id: Optional[str] = None
    customer: str
    email: str
    phone: Optional[str] = None
    date: Optional[str] = None
    total: float
    status: Optional[str] = "Processing"
    paymentMethod: Optional[str] = "Cash on Delivery"
    paymentStatus: Optional[str] = "Pending"
    address: Optional[str] = None
    items: List[OrderItem] = Field(default_factory=list)
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None
    currency: Optional[str] = "INR"
    paid_at: Optional[str] = None
    notes: Optional[str] = None

class OrderStatusUpdate(BaseModel):
    status: str
    paymentStatus: Optional[str] = None

class OrderOut(BaseModel):
    id: str
    customer: str
    email: str
    phone: Optional[str] = None
    date: str
    total: float
    status: str
    paymentMethod: str
    paymentStatus: Optional[str] = "Pending"
    address: Optional[str] = None
    items: List[OrderItem] = Field(default_factory=list)
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    currency: Optional[str] = "INR"
    paid_at: Optional[str] = None
    notes: Optional[str] = None

class RazorpayOrderCreateRequest(BaseModel):
    items: List[OrderItem]
    customer: str
    email: str
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    coupon_code: Optional[str] = None

class RazorpayPaymentVerifyRequest(BaseModel):
    order_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

class RazorpayPaymentFailedRequest(BaseModel):
    order_id: str
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    error_code: Optional[str] = None
    error_description: Optional[str] = None
    error_reason: Optional[str] = None

# ========================================================
# 6. Customer Schemas
# ========================================================
class CustomerOut(BaseModel):
    email: str
    customer: str
    phone: Optional[str] = None
    address: Optional[str] = None
    totalOrders: int = 0
    totalSpent: float = 0.0
    lastOrderDate: Optional[str] = None

# ========================================================
# 7. Homepage 9 Sections Schemas
# ========================================================
class AnnouncementSection(BaseModel):
    enabled: bool = True
    text: Optional[str] = None
    linkText: Optional[str] = None
    linkUrl: Optional[str] = None

class HeroSection(BaseModel):
    enabled: bool = True
    tag: Optional[str] = None
    title: Optional[str] = None
    desc: Optional[str] = None
    btn1Text: Optional[str] = None
    btn1Url: Optional[str] = None
    btn2Text: Optional[str] = None
    btn2Url: Optional[str] = None
    bgImg: Optional[str] = None

class CategoriesSection(BaseModel):
    enabled: bool = True
    tag: Optional[str] = None
    title: Optional[str] = None

class NewArrivalsSection(BaseModel):
    enabled: bool = True
    tag: Optional[str] = None
    title: Optional[str] = None
    count: Optional[int] = 4

class FeaturedSection(BaseModel):
    enabled: bool = True
    tag: Optional[str] = None
    title: Optional[str] = None
    desc: Optional[str] = None
    img: Optional[str] = None
    btnText: Optional[str] = None
    btnUrl: Optional[str] = None
    stat1Num: Optional[str] = None
    stat1Label: Optional[str] = None
    stat2Num: Optional[str] = None
    stat2Label: Optional[str] = None
    stat3Num: Optional[str] = None
    stat3Label: Optional[str] = None

class WhyChooseUsItem(BaseModel):
    icon: str
    title: str
    desc: str

class WhyChooseUsSection(BaseModel):
    enabled: bool = True
    tag: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    items: List[WhyChooseUsItem] = Field(default_factory=list)

class ReviewsSectionConfig(BaseModel):
    enabled: bool = True
    tag: Optional[str] = None
    title: Optional[str] = None

class InstagramSection(BaseModel):
    enabled: bool = True
    tag: Optional[str] = None
    handle: Optional[str] = None
    subtitle: Optional[str] = None
    images: List[str] = Field(default_factory=list)

class FooterSection(BaseModel):
    enabled: bool = True
    tagline: Optional[str] = None
    copyright: Optional[str] = None

class HomepageConfig(BaseModel):
    announcement: Optional[AnnouncementSection] = None
    hero: Optional[HeroSection] = None
    categories: Optional[CategoriesSection] = None
    newArrivals: Optional[NewArrivalsSection] = None
    featured: Optional[FeaturedSection] = None
    whyChooseUs: Optional[WhyChooseUsSection] = None
    reviewsSection: Optional[ReviewsSectionConfig] = None
    instagram: Optional[InstagramSection] = None
    footer: Optional[FooterSection] = None

# ========================================================
# 8. Settings Schemas
# ========================================================
class SocialLinks(BaseModel):
    instagram: Optional[str] = ""
    whatsapp: Optional[str] = ""
    pinterest: Optional[str] = ""
    facebook: Optional[str] = ""

class StoreSettings(BaseModel):
    siteName: str = "Dazzle by Dua"
    tagline: str = "Fine Jewellery"
    email: str = "contact@dazzlebydua.com"
    phone: str = "+91 98765 43210"
    address: str = "Shop 4, Luxury Arcade, Bandra West, Mumbai, MH 400050"
    currency: str = "?"
    freeShippingThreshold: float = 2500
    logoText: Optional[str] = "Dazzle by Dua"
    social: Optional[SocialLinks] = Field(default_factory=SocialLinks)

# ========================================================
# 9. Navigation Schemas
# ========================================================
class NavItem(BaseModel):
    name: str
    href: str

class NavigationConfig(BaseModel):
    header: List[NavItem] = Field(default_factory=list)
    footerQuick: List[NavItem] = Field(default_factory=list)
    footerCare: List[NavItem] = Field(default_factory=list)

# ========================================================
# 10. Pages Schemas
# ========================================================
class FAQItem(BaseModel):
    q: str
    a: str

class PagesContent(BaseModel):
    care_guide: Optional[str] = None
    shipping_terms: Optional[str] = None
    privacy_policy: Optional[str] = None
    terms_conditions: Optional[str] = None
    faqs: Optional[List[FAQItem]] = Field(default_factory=list)

# ========================================================
# 11. Media Schemas
# ========================================================
class MediaOut(BaseModel):
    id: int
    filename: str
    title: str
    type: str
    url: str
    size: int
    mime_type: Optional[str] = None
    created_at: str

# ========================================================
# 12. Auth & Admin Schemas
# ========================================================
class AdminLoginRequest(BaseModel):
    username: str
    password: str
    rememberMe: Optional[bool] = False

class AdminProfile(BaseModel):
    user: str
    email: str
    role: str

class AdminLoginResponse(BaseModel):
    success: bool
    user: AdminProfile
    token: str
    loginTime: str

# ========================================================
# 13. Dashboard Stats Schemas
# ========================================================
class DashboardStatsOut(BaseModel):
    totalRevenue: float
    totalOrders: int
    totalProducts: int
    outOfStockCount: int
    totalReviews: int
    pendingReviews: int
    avgRating: float
    totalCustomers: int
    recentOrders: List[OrderOut]
    lowStockProducts: List[ProductOut]
    recentReviews: List[ReviewOut]
