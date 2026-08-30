"""Seed demo data matching the reference scenario in ATOAC_ARCHITECTURE.md §25.

Run:  python seed.py
Creates two merchants, one buyer, chair products on both merchants, a desk-mat
upsell product on merchant B, and the 30+ qty upsell rule.

Logins (password for all): password123
  merchant A:  a@comfortseating.com
  merchant B:  b@workspacedirect.com
  buyer:       buyer@test.com
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

        m_a = User(email="a@comfortseating.com", password_hash=hash_password(PASSWORD),
                   role="merchant", business_name="Comfort Seating")
        m_b = User(email="b@workspacedirect.com", password_hash=hash_password(PASSWORD),
                   role="merchant", business_name="WorkSpace Direct")
        buyer = User(email="buyer@test.com", password_hash=hash_password(PASSWORD),
                     role="buyer", business_name=None)
        db.add_all([m_a, m_b, buyer])
        db.commit()

        chair_a = Product(merchant_id=m_a.id, name="Ergonomic Office Chair",
                          description="Mesh-back ergonomic chair", list_price=4800, floor_price=4400,
                          max_discount_pct=10, min_order_qty=1, max_negotiation_rounds=3,
                          stock=200, delivery_days=5, atoac_enabled=True)
        chair_b = Product(merchant_id=m_b.id, name="Ergonomic Office Chair",
                          description="Mesh-back ergonomic chair", list_price=4600, floor_price=4200,
                          max_discount_pct=10, min_order_qty=1, max_negotiation_rounds=3,
                          stock=200, delivery_days=7, atoac_enabled=True)
        desk_mat = Product(merchant_id=m_b.id, name="Desk Mat",
                           description="Premium felt desk mat", list_price=225, floor_price=180,
                           max_discount_pct=15, min_order_qty=1, max_negotiation_rounds=2,
                           stock=500, delivery_days=7, atoac_enabled=True)
        db.add_all([chair_a, chair_b, desk_mat])
        db.commit()

        db.add(UpsellRule(merchant_id=m_b.id, base_product_id=chair_b.id,
                          upsell_product_id=desk_mat.id, trigger_min_qty=30))
        db.commit()

        print("Seeded 2 merchants, 1 buyer, 3 products, 1 upsell rule.")
        print("Logins (password123): a@comfortseating.com, b@workspacedirect.com, buyer@test.com")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
