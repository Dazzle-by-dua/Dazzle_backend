# ========================================================
# DAZZLE BY DUA - Default Seed Data
# Exact match with frontend DEFAULT_* objects in script.js
# ========================================================

DEFAULT_ADMINS = [
    {
        "username": "admin",
        "email": "admin@dazzlebydua.com",
        "password": "admin123",
        "name": "Dua",
        "role": "Master Administrator"
    },
    {
        "username": "dua",
        "email": "dua@dazzlebydua.com",
        "password": "dazzleadmin",
        "name": "Dua",
        "role": "Store Owner"
    }
]

DEFAULT_PRODUCTS = [
    {
        "id": 1,
        "name": "Flower Pendant Necklace",
        "price": 4990,
        "oldPrice": 6990,
        "category": "necklaces",
        "rating": 4.8,
        "reviews": 24,
        "img": "product_flower_necklace.jpg",
        "badges": ["bestseller"],
        "inStock": True,
        "sku": "DBD-NC-001",
        "material": "18K Champagne Gold Vermeil & Natural Freshwater Pearl",
        "dimensions": "Pendant 18mm x 18mm | Chain length: 42cm + 5cm extension",
        "description": "An ode to blooming elegance, this Flower Pendant Necklace features delicately sculpted petals set with shimmering pavé accents, culminating in a radiant freshwater pearl at the center. Hand-crafted and finished in our signature 18K champagne gold vermeil.",
        "variants": ["18K Champagne Gold", "Rose Gold Vermeil", "Sterling Silver"],
        "images": ["product_flower_necklace.jpg", "hero_necklace.jpg", "featured_collection.jpg"]
    },
    {
        "id": 2,
        "name": "Pearl Drop Earrings",
        "price": 3990,
        "oldPrice": 5990,
        "category": "earrings",
        "rating": 4.9,
        "reviews": 18,
        "img": "product_pearl_earrings.jpg",
        "badges": ["new"],
        "inStock": True,
        "sku": "DBD-ER-002",
        "material": "18K Gold Plated Brass & Grade-AAA Freshwater Pearls",
        "dimensions": "Drop length: 32mm | Pearl diameter: 9mm",
        "description": "Graceful and captivating, the Pearl Drop Earrings frame your features with luminous freshwater pearls suspended from delicate diamond-accented hoop huggies. Designed to move subtly with your every step.",
        "variants": ["18K Champagne Gold", "Classic White Gold"],
        "images": ["product_pearl_earrings.jpg", "featured_collection.jpg", "hero_necklace.jpg"]
    },
    {
        "id": 3,
        "name": "Delicate Chain Bracelet",
        "price": 5990,
        "oldPrice": 7490,
        "category": "bracelets",
        "rating": 4.7,
        "reviews": 22,
        "img": "product_bracelet.jpg",
        "badges": [],
        "inStock": True,
        "sku": "DBD-BR-003",
        "material": "18K Champagne Gold Vermeil over Sterling Silver",
        "dimensions": "Length: 16cm + 3.5cm extender",
        "description": "Subtle luxury for every day. Our Delicate Chain Bracelet features fine interlocking links interwoven with dainty droplet charms that catch the light from every angle. Perfect for wearing solo or layering.",
        "variants": ["18K Champagne Gold", "Sterling Silver"],
        "images": ["product_bracelet.jpg", "featured_collection.jpg", "product_ring.jpg"]
    },
    {
        "id": 4,
        "name": "Minimal Diamond Ring",
        "price": 4690,
        "oldPrice": 6690,
        "category": "rings",
        "rating": 4.6,
        "reviews": 31,
        "img": "product_ring.jpg",
        "badges": ["sale"],
        "inStock": True,
        "sku": "DBD-RG-004",
        "material": "18K Champagne Gold Vermeil & Solitaire Cubic Zirconia",
        "dimensions": "Band width: 1.4mm | Solitaire: 4mm",
        "description": "The epitome of refined modern minimalism. This ring showcases a solitary brilliant-cut solitaire set upon an ultra-slim champagne gold band. Designed for seamless stacking or understated everyday luxury.",
        "variants": ["Size 6 (16.5mm)", "Size 7 (17.3mm)", "Size 8 (18.1mm)"],
        "images": ["product_ring.jpg", "featured_collection.jpg", "product_bracelet.jpg"]
    },
    {
        "id": 5,
        "name": "Gold Hoop Earrings",
        "price": 2990,
        "oldPrice": 3990,
        "category": "earrings",
        "rating": 4.5,
        "reviews": 15,
        "img": "product_pearl_earrings.jpg",
        "badges": [],
        "inStock": True,
        "sku": "DBD-ER-005",
        "material": "18K Champagne Gold Vermeil",
        "dimensions": "Diameter: 22mm | Thickness: 3mm",
        "description": "Timeless classic hoops reimagined with a modern sculpted silhouette. Lightweight enough for effortless day-to-night styling with a secure hinge clasp.",
        "variants": ["Small (18mm)", "Medium (22mm)", "Large (28mm)"],
        "images": ["product_pearl_earrings.jpg", "hero_necklace.jpg", "featured_collection.jpg"]
    },
    {
        "id": 6,
        "name": "Star Pendant Necklace",
        "price": 3490,
        "oldPrice": 4990,
        "category": "necklaces",
        "rating": 4.7,
        "reviews": 9,
        "img": "product_flower_necklace.jpg",
        "badges": ["new"],
        "inStock": False,
        "sku": "DBD-NC-006",
        "material": "18K Champagne Gold Vermeil",
        "dimensions": "Chain: 40cm + 5cm extension | Pendant: 12mm",
        "description": "Dainty celestial motif adorned with fine micropavé stones on a slender cable chain. Adds a celestial glow to your collarbone.",
        "variants": ["18K Champagne Gold", "Sterling Silver"],
        "images": ["product_flower_necklace.jpg", "hero_necklace.jpg", "featured_collection.jpg"]
    },
    {
        "id": 7,
        "name": "Pearl Stud Earrings",
        "price": 1990,
        "oldPrice": 2990,
        "category": "earrings",
        "rating": 4.8,
        "reviews": 42,
        "img": "product_pearl_earrings.jpg",
        "badges": ["bestseller"],
        "inStock": True,
        "sku": "DBD-ER-007",
        "material": "Grade-AAA Freshwater Pearls & 18K Gold Posts",
        "dimensions": "Diameter: 7mm",
        "description": "Effortless everyday classic. Handpicked button-shape freshwater pearls mounted on hypo-allergenic titanium posts with secure butterfly backs.",
        "variants": ["White Pearl", "Blush Pink Pearl"],
        "images": ["product_pearl_earrings.jpg", "featured_collection.jpg", "product_flower_necklace.jpg"]
    },
    {
        "id": 8,
        "name": "Bangle Bracelet Set",
        "price": 6990,
        "oldPrice": 8990,
        "category": "bracelets",
        "rating": 4.4,
        "reviews": 7,
        "img": "product_bracelet.jpg",
        "badges": ["offer"],
        "inStock": True,
        "sku": "DBD-BR-008",
        "material": "18K Champagne Gold Vermeil",
        "dimensions": "Inner diameter: 62mm (Medium)",
        "description": "A harmonized stack of finely textured bangles, each offering a different facet of hand-carved polish and champagne luster.",
        "variants": ["18K Champagne Gold", "Tricolor Gold Stack"],
        "images": ["product_bracelet.jpg", "featured_collection.jpg", "product_ring.jpg"]
    }
]

DEFAULT_CATEGORIES = [
    {"id": "necklaces", "name": "Necklaces", "count": 12, "img": "product_flower_necklace.jpg", "desc": "Graceful necklaces and pendants"},
    {"id": "earrings", "name": "Earrings", "count": 18, "img": "product_pearl_earrings.jpg", "desc": "Timeless pearl and gold drop earrings"},
    {"id": "bracelets", "name": "Bracelets", "count": 8, "img": "product_bracelet.jpg", "desc": "Delicate chain and bangle bracelets"},
    {"id": "rings", "name": "Rings", "count": 6, "img": "product_ring.jpg", "desc": "Understated luxury solitaire and stacking rings"}
]

DEFAULT_REVIEWS = [
    {"id": 1, "name": "Ayesha K.", "rating": 5, "text": "The Flower Pendant Necklace looks even prettier in person! Very good quality and beautiful packaging.", "date": "12 Jan 2025", "verified": True, "approved": True, "product": "Flower Pendant Necklace"},
    {"id": 2, "name": "Priya M.", "rating": 5, "text": "Absolutely love my pearl earrings. They are so delicate and elegant. Will definitely order again!", "date": "5 Feb 2025", "verified": True, "approved": True, "product": "Pearl Drop Earrings"},
    {"id": 3, "name": "Nadia R.", "rating": 4, "text": "Beautiful bracelet, perfect gift for my sister. The champagne gold finish is exactly as shown.", "date": "20 Mar 2025", "verified": True, "approved": True, "product": "Delicate Chain Bracelet"},
    {"id": 4, "name": "Sarah L.", "rating": 5, "text": "Dazzle by Dua is my go-to for jewellery! The quality is premium and the designs are timeless.", "date": "8 Apr 2025", "verified": True, "approved": True, "product": "Flower Pendant Necklace"},
    {"id": 5, "name": "Fatima Z.", "rating": 5, "text": "Ordered the ring and it arrived in gorgeous packaging. The detail is exquisite — absolutely stunning!", "date": "15 May 2025", "verified": True, "approved": True, "product": "Minimal Diamond Ring"},
    {"id": 6, "name": "Maha B.", "rating": 4, "text": "Very happy with my purchase. The earrings are lightweight and comfortable for all-day wear.", "date": "2 Jun 2025", "verified": True, "approved": True, "product": "Gold Hoop Earrings"}
]

DEFAULT_OFFERS = {
    "coupons": [
        {"id": "c1", "code": "DAZZLE10", "title": "Welcome Privilege", "discount": 10, "type": "percent", "minOrder": 1500, "expiry": "2026-12-31", "desc": "Receive 10% off your entire first purchase across all collections.", "badge": "First Order", "active": True},
        {"id": "c2", "code": "COMBO20", "title": "Selected Combos", "discount": 20, "type": "percent", "minOrder": 5000, "expiry": "2026-12-31", "desc": "Save 20% when you buy paired jewellery sets and matching duo sets.", "badge": "Combo Deal", "active": True},
        {"id": "c3", "code": "FREESHIP", "title": "Complimentary Express", "discount": 0, "type": "free_shipping", "minOrder": 2500, "expiry": "2026-12-31", "desc": "Complimentary express shipping across India with signature luxury box.", "badge": "Complimentary", "active": True}
    ],
    "combos": [
        {
            "id": "cb1",
            "name": "The Bridal Set",
            "discount": "30% OFF",
            "price": 10990,
            "oldPrice": 14970,
            "items": ["Flower Pendant Necklace", "Pearl Drop Earrings", "Delicate Chain Bracelet"],
            "images": ["product_flower_necklace.jpg", "product_pearl_earrings.jpg", "product_bracelet.jpg"]
        },
        {
            "id": "cb2",
            "name": "The Everyday Duo",
            "discount": "20% OFF",
            "price": 8540,
            "oldPrice": 10680,
            "items": ["Minimal Diamond Ring", "Delicate Chain Bracelet"],
            "images": ["product_ring.jpg", "product_bracelet.jpg"]
        },
        {
            "id": "cb3",
            "name": "The Gift Set",
            "discount": "25% OFF",
            "price": 6740,
            "oldPrice": 8980,
            "items": ["Pearl Drop Earrings", "Minimal Diamond Ring", "Premium Gift Box & Card"],
            "images": ["product_pearl_earrings.jpg", "product_ring.jpg"]
        }
    ]
}

DEFAULT_HOMEPAGE = {
    "announcement": {
        "enabled": True,
        "text": "Free shipping on orders above ₹2,500 | Use code DAZZLE10 for 10% off",
        "linkText": "View Offers →",
        "linkUrl": "offers.html"
    },
    "hero": {
        "enabled": True,
        "tag": "✦ New Collection 2026",
        "title": "Jewellery That <em>Tells</em><br>Your Story",
        "desc": "Discover pieces made to be remembered. Crafted with love, worn with grace.",
        "btn1Text": "Shop Collection →",
        "btn1Url": "shop.html",
        "btn2Text": "View Offers",
        "btn2Url": "offers.html",
        "bgImg": "hero_necklace.jpg"
    },
    "categories": {
        "enabled": True,
        "tag": "Shop by Category",
        "title": "Find Your Perfect Piece"
    },
    "newArrivals": {
        "enabled": True,
        "tag": "Just Arrived",
        "title": "New Arrivals",
        "count": 4
    },
    "featured": {
        "enabled": True,
        "tag": "Our Featured Collection",
        "title": "Grace in <em>Every</em> Detail",
        "desc": "Thoughtfully designed, beautifully crafted — our collection brings elegance to your everyday and special moments. Each piece tells a story of timeless beauty.",
        "img": "featured_collection.jpg",
        "btnText": "Explore Collection →",
        "btnUrl": "shop.html",
        "stat1Num": "500+",
        "stat1Label": "Happy Customers",
        "stat2Num": "50+",
        "stat2Label": "Unique Designs",
        "stat3Num": "4.8★",
        "stat3Label": "Avg. Rating"
    },
    "whyChooseUs": {
        "enabled": True,
        "tag": "Why Choose Us",
        "title": "The Dazzle Difference",
        "subtitle": "Thoughtfully chosen, beautifully packed, and delivered with care.",
        "items": [
            {"icon": "fa-gem", "title": "Premium Quality", "desc": "Each piece crafted with the finest materials and meticulous attention to detail."},
            {"icon": "fa-palette", "title": "Curated Designs", "desc": "Timeless, elegant designs that pair beautifully with any occasion or style."},
            {"icon": "fa-gift", "title": "Gift-Ready Packaging", "desc": "Want to gift it to someone special? Let us know while placing your order, and we'll prepare it in beautiful gift-ready packaging."},
            {"icon": "fa-truck-fast", "title": "Secure & Careful Delivery", "desc": "Every piece is carefully packed and secured to reach you safely and beautifully."}
        ]
    },
    "reviewsSection": {
        "enabled": True,
        "tag": "Customer Love",
        "title": "What Our Customers Say"
    },
    "instagram": {
        "enabled": True,
        "tag": "Follow Our Journey",
        "handle": "@dazzlebydua",
        "subtitle": "Share your Dazzle moments with us",
        "images": ["product_flower_necklace.jpg", "product_pearl_earrings.jpg", "product_bracelet.jpg", "product_ring.jpg"]
    },
    "footer": {
        "enabled": True,
        "tagline": "Timeless pieces, crafted with love.<br>For your most beautiful moments.",
        "copyright": "© 2025 Dazzle by Dua. All rights reserved."
    }
}

DEFAULT_ORDERS = [
    {
        "id": "DBD-2025-001",
        "customer": "Ayesha Khan",
        "email": "ayesha.k@example.com",
        "phone": "+91 98765 43210",
        "date": "10 Jan 2025",
        "total": 8980,
        "status": "Delivered",
        "paymentMethod": "UPI / Online",
        "address": "Flat 402, Sea Green Apts, Bandra West, Mumbai, MH 400050",
        "items": [
            {"id": 1, "name": "Flower Pendant Necklace", "price": 4990, "qty": 1, "variant": "Champagne Gold", "img": "product_flower_necklace.jpg"},
            {"id": 2, "name": "Pearl Drop Earrings", "price": 3990, "qty": 1, "variant": "Gold", "img": "product_pearl_earrings.jpg"}
        ]
    },
    {
        "id": "DBD-2025-002",
        "customer": "Priya Sharma",
        "email": "priya.s@example.com",
        "phone": "+91 98123 45678",
        "date": "18 Mar 2025",
        "total": 5990,
        "status": "Shipped",
        "paymentMethod": "Credit Card",
        "address": "74 Silver Birch, Indiranagar, Bengaluru, KA 560038",
        "items": [
            {"id": 3, "name": "Delicate Chain Bracelet", "price": 5990, "qty": 1, "variant": "Gold", "img": "product_bracelet.jpg"}
        ]
    },
    {
        "id": "DBD-2025-003",
        "customer": "Fatima Zahra",
        "email": "fatima.z@example.com",
        "phone": "+91 97654 32109",
        "date": "25 Sep 2025",
        "total": 4690,
        "status": "Processing",
        "paymentMethod": "Cash on Delivery",
        "address": "12 Gulmohar Lane, Jubilee Hills, Hyderabad, TS 500033",
        "items": [
            {"id": 4, "name": "Minimal Diamond Ring", "price": 4690, "qty": 1, "variant": "Size 7", "img": "product_ring.jpg"}
        ]
    }
]

DEFAULT_SETTINGS = {
    "siteName": "Dazzle by Dua",
    "tagline": "Fine Jewellery",
    "email": "contact@dazzlebydua.com",
    "phone": "+91 98765 43210",
    "address": "Shop 4, Luxury Arcade, Bandra West, Mumbai, MH 400050",
    "currency": "₹",
    "freeShippingThreshold": 2500,
    "logoText": "Dazzle by Dua",
    "social": {
        "instagram": "https://instagram.com/dazzlebydua",
        "whatsapp": "https://wa.me/919876543210",
        "pinterest": "#",
        "facebook": "#"
    }
}

DEFAULT_NAVIGATION = {
    "header": [
        {"name": "Home", "href": "index.html"},
        {"name": "Shop", "href": "shop.html"},
        {"name": "Offers", "href": "offers.html"},
        {"name": "My Orders", "href": "orders.html"},
        {"name": "Wishlist", "href": "wishlist.html"},
        {"name": "Contact", "href": "contact.html"}
    ],
    "footerQuick": [
        {"name": "Home", "href": "index.html"},
        {"name": "Shop", "href": "shop.html"},
        {"name": "Offers & Combos", "href": "offers.html"},
        {"name": "Contact Us", "href": "contact.html"},
        {"name": "My Orders", "href": "orders.html"},
        {"name": "Wishlist", "href": "wishlist.html"}
    ],
    "footerCare": [
        {"name": "Shipping Info", "href": "contact.html"},
        {"name": "Returns & Refunds", "href": "contact.html"},
        {"name": "Privacy Policy", "href": "#"},
        {"name": "Terms & Conditions", "href": "#"},
        {"name": "FAQs", "href": "contact.html"}
    ]
}

DEFAULT_PAGES = {
    "care_guide": "To preserve your jewellery's brilliance, keep away from direct contact with perfumes, sanitizers, chlorine, and harsh chemicals. Store individually when not in use. Gently buff with a clean microfiber cloth after wear.",
    "shipping_terms": "Your jewellery is carefully packed in secure packaging to help ensure it reaches you safely. Orders are dispatched with care and delivered through our available shipping service.",
    "privacy_policy": "We value your privacy. Your personal information is only used to fulfill your orders and enhance your experience. We never share or sell personal data.",
    "terms_conditions": "All designs, jewellery imagery, and branding are the exclusive property of Dazzle by Dua. Prices and promotions are subject to change without notice.",
    "faqs": [
        {"q": "How do I care for my gold vermeil jewellery?", "a": "Avoid direct contact with water, perfume, lotions, and harsh chemicals. Store in your Dazzle pouch."},
        {"q": "What are the shipping charges and delivery timelines?", "a": "We offer complimentary express shipping on all orders above ₹2,500. Delivery takes 3-5 business days across India."},
        {"q": "What is your return & exchange policy?", "a": "We accept returns and exchanges within 7 days of delivery for unworn items in original packaging."}
    ]
}
