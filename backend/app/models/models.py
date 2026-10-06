from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Dish(Base):
    __tablename__ = "dishes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    portion_unit: Mapped[str] = mapped_column(String(16), default="份")

class Ingredient(Base):
    __tablename__ = "ingredients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16), default="kg")
    stock_qty: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_qty: Mapped[float] = mapped_column(Float, default=0.0)

class BomLine(Base):
    __tablename__ = "bom_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    qty_per_portion: Mapped[float] = mapped_column(Float)

class KitchenOrder(Base):
    __tablename__ = "kitchen_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    outlet: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="open")

class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    portions: Mapped[int] = mapped_column(Integer)

class PrepRun(Base):
    """BOM 展开快照，一经生成不可变；仅作存档留痕，手改备料单不回写这里。"""
    __tablename__ = "prep_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")

class PrepDoc(Base):
    """可手改的备料单工作副本。status: open(可改) / archived(存档) / voided(作废)。"""
    __tablename__ = "prep_docs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    prep_run_id: Mapped[int] = mapped_column(ForeignKey("prep_runs.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lines: Mapped[list["PrepLine"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan"
    )

class PrepLine(Base):
    """备料单行。need_qty 为 BOM 需求上限（不可越过）；qty 与 reserved_qty 永远同值联动。"""
    __tablename__ = "prep_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("prep_docs.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    need_qty: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    reserved_qty: Mapped[float] = mapped_column(Float)
    doc: Mapped[PrepDoc] = relationship(back_populates="lines")
