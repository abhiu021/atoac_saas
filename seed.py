"""Seed demo data with 4 merchants, 40+ products, and sample negotiations.

Run:  python seed.py
Creates four merchants with diverse product catalogs, one buyer, and multiple products.

Logins (password for all): password123
  Merchant A (Comfort Seating):    a@comfortseating.com
  Merchant B (WorkSpace Direct):   b@workspacedirect.com
  Merchant C (Office Plus):        c@officeplus.com
  Merchant D (Tech Supplies):      d@techsupplies.com
  Buyer:                           buyer@test.com
"""
from auth import hash_password
from database import SessionLocal, init_db
from models import Product, UpsellRule, User

PASSWORD = "password123"


def seed():
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == "buyer@test.com").first():
            print("Seed data already present — skipping.")
            return

        # Create merchants
        m_a = User(email="a@comfortseating.com", password_hash=hash_password(PASSWORD),
                   role="merchant", business_name="Comfort Seating")
        m_b = User(email="b@workspacedirect.com", password_hash=hash_password(PASSWORD),
                   role="merchant", business_name="WorkSpace Direct")
        m_c = User(email="c@officeplus.com", password_hash=hash_password(PASSWORD),
                   role="merchant", business_name="Office Plus")
        m_d = User(email="d@techsupplies.com", password_hash=hash_password(PASSWORD),
                   role="merchant", business_name="Tech Supplies")
        buyer = User(email="buyer@test.com", password_hash=hash_password(PASSWORD),
                     role="buyer", business_name=None)
        db.add_all([m_a, m_b, m_c, m_d, buyer])
        db.commit()

        # MERCHANT A: COMFORT SEATING - Furniture Focus
        products_a = [
            Product(merchant_id=m_a.id, name="Ergonomic Office Chair",
                    description="Premium mesh-back ergonomic chair with lumbar support", 
                    list_price=4800, floor_price=4200, max_discount_pct=12, min_order_qty=1,
                    stock=150, delivery_days=5, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Office+Chair"),
            Product(merchant_id=m_a.id, name="Executive Leather Chair",
                    description="High-back leather executive chair for premium offices",
                    list_price=8500, floor_price=7200, max_discount_pct=15, min_order_qty=1,
                    stock=45, delivery_days=7, strategy="firm",
                    image_url="https://via.placeholder.com/300x300?text=Leather+Chair"),
            Product(merchant_id=m_a.id, name="Conference Room Chair",
                    description="Stackable conference chairs in grey upholstery",
                    list_price=1200, floor_price=950, max_discount_pct=20, min_order_qty=5,
                    stock=200, delivery_days=4, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Conference+Chair"),
            Product(merchant_id=m_a.id, name="Standing Desk Frame",
                    description="Electric adjustable standing desk frame - dual motor",
                    list_price=3200, floor_price=2800, max_discount_pct=12, min_order_qty=1,
                    stock=80, delivery_days=6, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Desk+Frame"),
            Product(merchant_id=m_a.id, name="Desk Chair Mat",
                    description="Premium PVC desk chair mat - anti-slip backing",
                    list_price=450, floor_price=350, max_discount_pct=22, min_order_qty=2,
                    stock=500, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Chair+Mat"),
            Product(merchant_id=m_a.id, name="Monitor Arm Stand",
                    description="Adjustable VESA monitor arm for single display",
                    list_price=850, floor_price=680, max_discount_pct=20, min_order_qty=1,
                    stock=120, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Monitor+Arm"),
            Product(merchant_id=m_a.id, name="Desk Organizer Tray",
                    description="Multi-compartment desktop organizer in walnut",
                    list_price=280, floor_price=220, max_discount_pct=25, min_order_qty=3,
                    stock=300, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Organizer"),
            Product(merchant_id=m_a.id, name="Ergonomic Keyboard",
                    description="Mechanical ergonomic keyboard with wrist rest",
                    list_price=1200, floor_price=950, max_discount_pct=18, min_order_qty=1,
                    stock=200, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Keyboard"),
            Product(merchant_id=m_a.id, name="Mouse Pad with Wrist Support",
                    description="Large extended mouse pad with ergonomic wrist rest",
                    list_price=320, floor_price=250, max_discount_pct=22, min_order_qty=2,
                    stock=400, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Mouse+Pad"),
            Product(merchant_id=m_a.id, name="Desk Lamp LED",
                    description="Adjustable LED desk lamp - 5 brightness levels",
                    list_price=680, floor_price=540, max_discount_pct=20, min_order_qty=1,
                    stock=250, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Desk+Lamp"),
            Product(merchant_id=m_a.id, name="Cable Management Kit",
                    description="Complete cable organizer set with clips and ties",
                    list_price=420, floor_price=320, max_discount_pct=24, min_order_qty=2,
                    stock=350, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Cable+Kit"),
            Product(merchant_id=m_a.id, name="Monitor Stand Riser",
                    description="Adjustable monitor stand with storage compartment",
                    list_price=950, floor_price=750, max_discount_pct=20, min_order_qty=1,
                    stock=100, delivery_days=5, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Monitor+Riser"),
        ]
        db.add_all(products_a)
        db.commit()

        # MERCHANT B: WORKSPACE DIRECT - Office Supplies & Furniture
        products_b = [
            Product(merchant_id=m_b.id, name="Ergonomic Office Chair",
                    description="Mesh back ergonomic chair - premium quality",
                    list_price=4600, floor_price=4000, max_discount_pct=12, min_order_qty=1,
                    stock=200, delivery_days=7, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Office+Chair+B"),
            Product(merchant_id=m_b.id, name="Desk Mat",
                    description="Premium felt desk pad - 60x40cm",
                    list_price=225, floor_price=180, max_discount_pct=20, min_order_qty=1,
                    stock=600, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Desk+Mat"),
            Product(merchant_id=m_b.id, name="Filing Cabinet",
                    description="4-drawer steel filing cabinet - lockable",
                    list_price=5200, floor_price=4500, max_discount_pct=12, min_order_qty=1,
                    stock=60, delivery_days=10, strategy="firm",
                    image_url="https://via.placeholder.com/300x300?text=Filing+Cabinet"),
            Product(merchant_id=m_b.id, name="Office Storage Shelf",
                    description="5-tier metal storage rack - industrial strength",
                    list_price=2800, floor_price=2300, max_discount_pct=18, min_order_qty=1,
                    stock=90, delivery_days=7, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Storage+Shelf"),
            Product(merchant_id=m_b.id, name="Desk Organizer",
                    description="Multi-tier desk organizer for files and papers",
                    list_price=380, floor_price=300, max_discount_pct=21, min_order_qty=2,
                    stock=250, delivery_days=4, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Desk+Organizer"),
            Product(merchant_id=m_b.id, name="Document Tray Set",
                    description="Set of 3 stackable document trays",
                    list_price=520, floor_price=410, max_discount_pct=21, min_order_qty=1,
                    stock=180, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Document+Tray"),
            Product(merchant_id=m_b.id, name="Paper Shredder",
                    description="Heavy-duty paper shredder - cross-cut",
                    list_price=3500, floor_price=2900, max_discount_pct=17, min_order_qty=1,
                    stock=40, delivery_days=7, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Shredder"),
            Product(merchant_id=m_b.id, name="Whiteboard with Stand",
                    description="Portable magnetic whiteboard with stand",
                    list_price=1200, floor_price=950, max_discount_pct=20, min_order_qty=1,
                    stock=75, delivery_days=5, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Whiteboard"),
            Product(merchant_id=m_b.id, name="Bulletin Board Set",
                    description="Cork bulletin board with frame",
                    list_price=680, floor_price=540, max_discount_pct=20, min_order_qty=1,
                    stock=120, delivery_days=4, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Bulletin+Board"),
            Product(merchant_id=m_b.id, name="Wall-mounted Shelving",
                    description="Wall-mounted metal shelf - 120cm",
                    list_price=1850, floor_price=1450, max_discount_pct=21, min_order_qty=1,
                    stock=100, delivery_days=6, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Wall+Shelf"),
            Product(merchant_id=m_b.id, name="Desk Partition Screen",
                    description="Privacy desk partition - fabric covered",
                    list_price=2200, floor_price=1800, max_discount_pct=18, min_order_qty=1,
                    stock=50, delivery_days=8, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Partition"),
            Product(merchant_id=m_b.id, name="Office Chair Cushion",
                    description="Premium memory foam chair cushion",
                    list_price=420, floor_price=330, max_discount_pct=21, min_order_qty=2,
                    stock=300, delivery_days=4, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Cushion"),
        ]
        db.add_all(products_b)
        db.commit()

        # MERCHANT C: OFFICE PLUS - General Office Equipment
        products_c = [
            Product(merchant_id=m_c.id, name="Multifunction Printer",
                    description="All-in-one color printer, copier, scanner",
                    list_price=18500, floor_price=15800, max_discount_pct=14, min_order_qty=1,
                    stock=25, delivery_days=8, strategy="firm",
                    image_url="https://via.placeholder.com/300x300?text=Printer"),
            Product(merchant_id=m_c.id, name="Desktop Computer Tower",
                    description="High-performance desktop for office use",
                    list_price=42000, floor_price=36000, max_discount_pct=14, min_order_qty=1,
                    stock=15, delivery_days=5, strategy="firm",
                    image_url="https://via.placeholder.com/300x300?text=Computer"),
            Product(merchant_id=m_c.id, name="24-inch LED Monitor",
                    description="Full HD IPS display monitor",
                    list_price=8900, floor_price=7500, max_discount_pct=15, min_order_qty=1,
                    stock=80, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Monitor"),
            Product(merchant_id=m_c.id, name="Office Phone System",
                    description="Digital phone system for office",
                    list_price=5500, floor_price=4600, max_discount_pct=16, min_order_qty=1,
                    stock=35, delivery_days=7, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Phone+System"),
            Product(merchant_id=m_c.id, name="CCTV Security Camera",
                    description="4K security camera for office",
                    list_price=12000, floor_price=10000, max_discount_pct=16, min_order_qty=1,
                    stock=40, delivery_days=6, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Camera"),
            Product(merchant_id=m_c.id, name="Access Control System",
                    description="Electronic access control for doors",
                    list_price=8800, floor_price=7400, max_discount_pct=16, min_order_qty=1,
                    stock=20, delivery_days=9, strategy="firm",
                    image_url="https://via.placeholder.com/300x300?text=Access+Control"),
            Product(merchant_id=m_c.id, name="Office Coffee Machine",
                    description="Commercial office coffee maker",
                    list_price=3200, floor_price=2700, max_discount_pct=15, min_order_qty=1,
                    stock=50, delivery_days=5, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Coffee+Machine"),
            Product(merchant_id=m_c.id, name="Water Cooler Dispenser",
                    description="5-gallon water cooler with heating/cooling",
                    list_price=4500, floor_price=3800, max_discount_pct=15, min_order_qty=1,
                    stock=45, delivery_days=6, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Water+Cooler"),
            Product(merchant_id=m_c.id, name="Fire Extinguisher",
                    description="ABC fire extinguisher - 2kg",
                    list_price=650, floor_price=520, max_discount_pct=20, min_order_qty=1,
                    stock=200, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Fire+Extinguisher"),
            Product(merchant_id=m_c.id, name="First Aid Kit",
                    description="Complete office first aid kit",
                    list_price=1850, floor_price=1500, max_discount_pct=19, min_order_qty=1,
                    stock=80, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=First+Aid"),
            Product(merchant_id=m_c.id, name="Emergency Exit Sign",
                    description="LED emergency exit sign with backup",
                    list_price=2200, floor_price=1800, max_discount_pct=18, min_order_qty=1,
                    stock=60, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Exit+Sign"),
            Product(merchant_id=m_c.id, name="Cleaning Supplies Kit",
                    description="Complete office cleaning supplies",
                    list_price=3800, floor_price=3100, max_discount_pct=18, min_order_qty=1,
                    stock=120, delivery_days=4, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Cleaning+Kit"),
        ]
        db.add_all(products_c)
        db.commit()

        # MERCHANT D: TECH SUPPLIES - IT Equipment & Cables
        products_d = [
            Product(merchant_id=m_d.id, name="USB Type-C Cable",
                    description="High-quality USB-C charging cable - 2m",
                    list_price=280, floor_price=220, max_discount_pct=21, min_order_qty=5,
                    stock=1000, delivery_days=2, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=USB+Cable"),
            Product(merchant_id=m_d.id, name="HDMI Cable",
                    description="4K HDMI 2.1 cable - 3m",
                    list_price=420, floor_price=330, max_discount_pct=21, min_order_qty=3,
                    stock=800, delivery_days=2, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=HDMI"),
            Product(merchant_id=m_d.id, name="Ethernet Cable",
                    description="Cat6A ethernet cable - 10m",
                    list_price=550, floor_price=440, max_discount_pct=20, min_order_qty=2,
                    stock=600, delivery_days=3, strategy="aggressive",
                    image_url="https://via.placeholder.com/300x300?text=Ethernet"),
            Product(merchant_id=m_d.id, name="Power Extension Board",
                    description="6-socket power extension with surge protection",
                    list_price=680, floor_price=540, max_discount_pct=20, min_order_qty=2,
                    stock=500, delivery_days=3, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Power+Board"),
            Product(merchant_id=m_d.id, name="Wireless Mouse",
                    description="Ergonomic wireless mouse with USB receiver",
                    list_price=850, floor_price=680, max_discount_pct=20, min_order_qty=1,
                    stock=300, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Wireless+Mouse"),
            Product(merchant_id=m_d.id, name="USB Hub",
                    description="7-port USB 3.0 hub with power supply",
                    list_price=1200, floor_price=950, max_discount_pct=21, min_order_qty=1,
                    stock=200, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=USB+Hub"),
            Product(merchant_id=m_d.id, name="Laptop Stand",
                    description="Adjustable aluminum laptop stand",
                    list_price=1450, floor_price=1150, max_discount_pct=20, min_order_qty=1,
                    stock=250, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Laptop+Stand"),
            Product(merchant_id=m_d.id, name="Wireless Keyboard",
                    description="Compact wireless keyboard with rechargeable battery",
                    list_price=1100, floor_price=880, max_discount_pct=20, min_order_qty=1,
                    stock=280, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Wireless+Keyboard"),
            Product(merchant_id=m_d.id, name="Laptop Cooling Pad",
                    description="5-fan laptop cooling pad",
                    list_price=1800, floor_price=1450, max_discount_pct=19, min_order_qty=1,
                    stock=150, delivery_days=4, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Cooling+Pad"),
            Product(merchant_id=m_d.id, name="External Hard Drive",
                    description="2TB USB 3.0 external hard drive",
                    list_price=4200, floor_price=3500, max_discount_pct=16, min_order_qty=1,
                    stock=100, delivery_days=3, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Hard+Drive"),
            Product(merchant_id=m_d.id, name="SSD Portable Storage",
                    description="1TB portable SSD - fast and compact",
                    list_price=5800, floor_price=4850, max_discount_pct=16, min_order_qty=1,
                    stock=120, delivery_days=3, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=SSD"),
            Product(merchant_id=m_d.id, name="Webcam HD",
                    description="1080p HD webcam with microphone",
                    list_price=2200, floor_price=1800, max_discount_pct=18, min_order_qty=1,
                    stock=180, delivery_days=3, strategy="balanced",
                    image_url="https://via.placeholder.com/300x300?text=Webcam"),
        ]
        db.add_all(products_d)
        db.commit()

        # Add upsell rules
        # Rule: When buying 30+ office chairs, offer desk mat
        chair_a = db.query(Product).filter(Product.name == "Ergonomic Office Chair",
                                           Product.merchant_id == m_a.id).first()
        cable_kit = db.query(Product).filter(Product.name == "Cable Management Kit",
                                             Product.merchant_id == m_a.id).first()
        if chair_a and cable_kit:
            db.add(UpsellRule(merchant_id=m_a.id, base_product_id=chair_a.id,
                            upsell_product_id=cable_kit.id, trigger_min_qty=30))

        chair_b = db.query(Product).filter(Product.name == "Ergonomic Office Chair",
                                           Product.merchant_id == m_b.id).first()
        desk_mat = db.query(Product).filter(Product.name == "Desk Mat",
                                            Product.merchant_id == m_b.id).first()
        if chair_b and desk_mat:
            db.add(UpsellRule(merchant_id=m_b.id, base_product_id=chair_b.id,
                            upsell_product_id=desk_mat.id, trigger_min_qty=30))

        db.commit()

        product_count = db.query(Product).count()
        merchant_count = db.query(User).filter(User.role == "merchant").count()
        print(f"✓ Seeded {merchant_count} merchants, 1 buyer, {product_count} products")
        print("Logins (password123):")
        print("  a@comfortseating.com     (Comfort Seating)")
        print("  b@workspacedirect.com    (WorkSpace Direct)")
        print("  c@officeplus.com         (Office Plus)")
        print("  d@techsupplies.com       (Tech Supplies)")
        print("  buyer@test.com           (Buyer)")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
