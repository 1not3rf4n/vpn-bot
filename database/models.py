# pyrefly: ignore [missing-import]
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, DateTime, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from datetime import datetime
from core.config import DB_URL

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True)
    fullname = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    is_admin = Column(Boolean, default=False)
    wallet_balance = Column(Float, default=0.0)
    joined_at = Column(DateTime, default=datetime.utcnow)
    referred_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)

    orders = relationship("Order", back_populates="user")
    services = relationship("Service", back_populates="user")
    tickets = relationship("Ticket", back_populates="user")
    referrals = relationship("User", backref="referred_by", remote_side=[id])

class Setting(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(Text, nullable=True)
    # Keys like: "start_message", "forced_channel", "admin_card"

class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    parent_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    is_active = Column(Boolean, default=True)
    delivery_msg = Column(Text, nullable=True)
    
    children = relationship("Category", backref="parent", remote_side=[id])
    products = relationship("Product", back_populates="category")

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey('categories.id'))
    name = Column(String(255))
    description = Column(Text, nullable=True)
    price = Column(Float, default=0.0) # Price in Toman
    duration_days = Column(Integer, default=30) # Subscription duration
    is_active = Column(Boolean, default=True)
    product_type = Column(String(50), default="VPN") # VPN, V2RAY
    panel_id = Column(Integer, nullable=True) # Inbound ID for X-UI
    volume_gb = Column(Float, default=0) # Traffic volume in GB (0 = unlimited)
    
    category = relationship("Category", back_populates="products")

class Service(Base):
    """Saves user's purchased VPNs or keys"""
    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    config_link = Column(Text, nullable=True)
    panel_username = Column(String(255), nullable=True)
    status = Column(String(50), default="ACTIVE")
    expire_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="services")

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    product_id = Column(Integer, ForeignKey('products.id'))
    amount = Column(Float)
    payment_method = Column(String(50))
    status = Column(String(50), default='PENDING')
    receipt_photo = Column(String(255), nullable=True)
    coupon_id = Column(Integer, nullable=True)
    gateway_authority = Column(String(255), nullable=True)
    gateway_tracking_id = Column(String(255), nullable=True)
    gateway_hash_id = Column(String(255), nullable=True)
    expire_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    custom_server_name = Column(String(100), nullable=True)

    user = relationship("User", back_populates="orders")
    
class Ticket(Base):
    __tablename__ = 'tickets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    department = Column(String(100), default="پشتیبانی")
    message = Column(Text)
    reply = Column(Text, nullable=True)
    status = Column(String(50), default="OPEN")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="tickets")
    
class FreeConfig(Base):
    __tablename__ = 'free_configs'
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=True)
    config_text = Column(String(500), nullable=True)
    country = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    config_data = Column(Text, nullable=True)
    is_claimed = Column(Boolean, default=False)
    claimed_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    expire_date = Column(DateTime, nullable=True) # Expiration date for the config
    created_at = Column(DateTime, default=datetime.utcnow)
    
class Receipt(Base):
    __tablename__ = 'receipts'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    amount = Column(Float)
    photo_id = Column(String(255))
    status = Column(String(50), default="PENDING")
    receipt_type = Column(String(50), default="TOPUP") # "TOPUP" or "ORDER"
    reference_id = Column(Integer, nullable=True) # E.g. Order ID if type is ORDER
    created_at = Column(DateTime, default=datetime.utcnow)

class CryptoNetwork(Base):
    __tablename__ = 'crypto_networks'
    id = Column(Integer, primary_key=True)
    name = Column(String(50)) # e.g. "Tether (USDT)"
    network = Column(String(50)) # e.g. "TRC20"
    address = Column(String(255)) # Wallet address
    is_active = Column(Boolean, default=True)

class DiscountCode(Base):
    __tablename__ = 'discount_codes'
    id = Column(Integer, primary_key=True)
    code = Column(String(100), unique=True)
    percent = Column(Float, default=0.0) # E.g. 10.0 for 10%
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    active = Column(Boolean, default=True)

class TestServerTemplate(Base):
    __tablename__ = 'test_server_templates'
    id = Column(Integer, primary_key=True)
    name_template = Column(String(100))  # base name e.g. 'test'
    volume_gb = Column(Float, default=0)
    duration_days = Column(Integer, default=1)
    inbound_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)

class TestServerAssignment(Base):
    __tablename__ = 'test_server_assignments'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    template_id = Column(Integer, ForeignKey('test_server_templates.id'), nullable=True)
    server_name = Column(String(150))
    panel_id = Column(Integer, nullable=True)
    expire_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    template = relationship("TestServerTemplate")

class XUIPanel(Base):
    __tablename__ = 'xuipanels'
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    url = Column(String(255))
    username = Column(String(100))
    password = Column(String(100))
    is_active = Column(Boolean, default=True)

engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    # Since Alembic will manage it, we could just rely on revisions. 
    # But for a quick start, we can still use create_all if no tables exist.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
