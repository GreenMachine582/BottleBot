from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    brand = Column(String)
    category = Column(String)
    subcategory = Column(String)
    volume_ml = Column(Integer)
    abv = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    retailer_products = relationship("RetailerProduct", back_populates="product")


class RetailerProduct(Base):
    __tablename__ = "retailer_products"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    retailer = Column(String, nullable=False)
    retailer_sku = Column(String)
    url = Column(Text, nullable=False)
    image_url = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    product = relationship("Product", back_populates="retailer_products")
    price_history = relationship("PriceHistory", back_populates="retailer_product")


class PriceHistory(Base):
    __tablename__ = "price_history"
    id = Column(Integer, primary_key=True)
    retailer_product_id = Column(Integer, ForeignKey("retailer_products.id"))
    price_aud = Column(Float, nullable=False)
    was_price_aud = Column(Float)
    in_stock = Column(Boolean, default=True)
    on_sale = Column(Boolean, default=False)
    promo_label = Column(String)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    retailer_product = relationship("RetailerProduct", back_populates="price_history")


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    status = Column(String)
    products_seen = Column(Integer, default=0)
    prices_inserted = Column(Integer, default=0)
    error_msg = Column(Text)
