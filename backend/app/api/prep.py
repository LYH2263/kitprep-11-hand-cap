import json
import math
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import (
    BomLine, Ingredient, KitchenOrder, OrderLine, PrepDoc, PrepLine, PrepRun,
)
from app.services.bom_engine import explode_and_merge, result_to_dict

router = APIRouter(prefix="/prep", tags=["prep"])

# 浮点口径：需求上限按三位小数存储，比较时留这一点容差。
EPS = 1e-6


class LineEdit(BaseModel):
    qty: float


def _explode(order_id: int, db: Session) -> dict:
    order = db.get(KitchenOrder, order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in db.scalars(select(Ingredient)).all()}
    result = result_to_dict(explode_and_merge(ols, bom, ings))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return result


def _serialize_doc(doc: PrepDoc, db: Session) -> dict:
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    order = db.get(KitchenOrder, doc.order_id)
    lines = []
    for l in sorted(doc.lines, key=lambda x: x.id):
        ing = ings[l.ingredient_id]
        lines.append({
            "id": l.id,
            "ingredient_id": l.ingredient_id,
            "ingredient_code": ing.code,
            "ingredient_name": ing.name,
            "unit": ing.unit,
            "stock_qty": round(ing.stock_qty, 3),
            "need_qty": round(l.need_qty, 3),
            "qty": round(l.qty, 3),
            "reserved_qty": round(l.reserved_qty, 3),
        })
    return {
        "id": doc.id,
        "order_id": doc.order_id,
        "order_code": order.code if order else None,
        "outlet": order.outlet if order else None,
        "prep_run_id": doc.prep_run_id,
        "status": doc.status,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "lines": lines,
    }


def _use_row_locks(db: Session) -> bool:
    # SQLite 无行锁且测试用单连接串行执行；PostgreSQL 等用 FOR UPDATE。
    return db.bind.dialect.name != "sqlite"


def _release(doc: PrepDoc, db: Session, lock_rows: bool) -> None:
    """释放整单占用。只在单据离开 open（存档/作废）时调用。"""
    # 按 ingredient_id 排序后再动，和手改/重新生成保持全局一致的加锁顺序，防死锁。
    for line in sorted(doc.lines, key=lambda x: x.ingredient_id):
        ing_q = select(Ingredient).where(Ingredient.id == line.ingredient_id)
        if lock_rows:
            ing_q = ing_q.with_for_update()
        ing = db.scalar(ing_q)
        if ing is None:
            continue
        ing.reserved_qty = max(0.0, round(ing.reserved_qty - line.reserved_qty, 6))


@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    result = _explode(order_id, db)

    # 1) 不可变快照存档留痕；手改永远不回写这里。
    run = PrepRun(order_id=order_id, created_at=datetime.utcnow(),
                  result_json=json.dumps(result, ensure_ascii=False))
    db.add(run)
    db.flush()

    # 2) 同一订单更早的 open 单整体存档并释放占用；已存档/已作废的单一字不动。
    use_locks = _use_row_locks(db)
    old_q = (
        select(PrepDoc)
        .where(PrepDoc.order_id == order_id, PrepDoc.status == "open")
        .order_by(PrepDoc.id)  # 固定多单加锁顺序，防并发 run 互相死锁
    )
    if use_locks:
        old_q = old_q.with_for_update()
    old_docs = db.scalars(old_q).all()
    for old in old_docs:
        _release(old, db, use_locks)
        old.status = "archived"

    # 3) 新工作单：需求 = 数量 = 占用，整单一起建。
    doc = PrepDoc(order_id=order_id, prep_run_id=run.id, status="open",
                  created_at=datetime.utcnow())
    db.add(doc)
    db.flush()
    for l in sorted(result["prep_lines"], key=lambda x: x["ingredient_id"]):
        db.add(PrepLine(
            doc_id=doc.id, ingredient_id=l["ingredient_id"],
            need_qty=l["need_qty"], qty=l["need_qty"], reserved_qty=l["need_qty"],
        ))
        ing_q = select(Ingredient).where(Ingredient.id == l["ingredient_id"])
        if use_locks:
            ing_q = ing_q.with_for_update()
        ing = db.scalar(ing_q)
        ing.reserved_qty = round(ing.reserved_qty + l["need_qty"], 6)

    db.commit()
    return {"id": run.id, **result}


@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    run = db.scalars(select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id.desc())).first()
    if not run:
        return run_prep(order_id=order_id, db=db)
    data = json.loads(run.result_json)
    return {"id": run.id, **data}


@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    data = latest(order_id=order_id, db=db)
    return {"order_id": order_id, "shortages": data.get("shortages", []), "stats": data.get("stats", {})}


@router.get("/docs")
def list_docs(order_id: int = 1, db: Session = Depends(get_db)):
    docs = db.scalars(
        select(PrepDoc).where(PrepDoc.order_id == order_id).order_by(PrepDoc.id.desc())
    ).all()
    return [_serialize_doc(d, db) for d in docs]


@router.get("/docs/active")
def active_doc(order_id: int = 1, db: Session = Depends(get_db)):
    doc = db.scalars(
        select(PrepDoc).where(PrepDoc.order_id == order_id, PrepDoc.status == "open")
        .order_by(PrepDoc.id.desc())
    ).first()
    return _serialize_doc(doc, db) if doc else None


@router.post("/docs/{doc_id}/lines/{line_id}")
def edit_line(doc_id: int, line_id: int, payload: LineEdit, db: Session = Depends(get_db)):
    """手改某一行数量。数量与占用要么一起改，要么整单退回、占用不动。"""
    qty = payload.qty

    # —— 全部校验先于任何写入，任一项不过即整单失败 ——
    doc = db.get(PrepDoc, doc_id)
    if doc is None:
        raise HTTPException(404, "备料单不存在")
    if doc.status == "voided":
        raise HTTPException(409, "备料单已作废，不能手改")
    if doc.status == "archived":
        raise HTTPException(409, "备料单已存档，不能手改")

    line = db.get(PrepLine, line_id)
    if line is None or line.doc_id != doc_id:
        # 找不到行：直接拒绝，不允许出现只改一半的状态。
        raise HTTPException(404, "备料单行不存在")

    if not math.isfinite(qty):
        raise HTTPException(422, "数量必须是有效数字")
    if qty < -EPS:
        raise HTTPException(422, "数量不能为负，整单未保存")
    qty = max(0.0, qty)
    if qty > line.need_qty + EPS:
        raise HTTPException(
            422,
            f"改后数量 {round(qty, 3)} 超过该行当前需求 {round(line.need_qty, 3)}，整单失败并退回，占用未动",
        )

    # —— 校验全过，进入写入段。锁顺序固定：prep_doc -> prep_line -> ingredient，
    # 作废/重新生成也按同一顺序抢锁，杜绝"检查 open 后被并发作废、占用被加回"。 ——
    use_locks = _use_row_locks(db)
    locked_doc = db.scalar(
        select(PrepDoc).where(PrepDoc.id == doc_id).with_for_update()
    ) if use_locks else doc
    if locked_doc.status != "open":
        # 持锁复检：可能在校验通过后刚被作废/存档。
        raise HTTPException(409, f"备料单已{('作废' if locked_doc.status == 'voided' else '存档')}，不能手改")

    locked_line = db.scalar(
        select(PrepLine).where(PrepLine.id == line_id).with_for_update()
    ) if use_locks else line
    if locked_line is None or locked_line.doc_id != doc_id:
        raise HTTPException(404, "备料单行不存在")

    ing_q = select(Ingredient).where(Ingredient.id == locked_line.ingredient_id)
    if use_locks:
        ing_q = ing_q.with_for_update()
    ing = db.scalar(ing_q)
    delta = round(qty - locked_line.qty, 6)
    if abs(delta) >= EPS:
        ing.reserved_qty = round(ing.reserved_qty + delta, 6)
    locked_line.qty = round(qty, 3)
    locked_line.reserved_qty = round(qty, 3)

    db.commit()
    db.refresh(doc)
    return _serialize_doc(doc, db)


@router.post("/docs/{doc_id}/void")
def void_doc(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(PrepDoc, doc_id)
    if doc is None:
        raise HTTPException(404, "备料单不存在")
    if doc.status == "voided":
        raise HTTPException(409, "备料单已作废")
    if doc.status == "archived":
        raise HTTPException(409, "备料单已存档，不能作废")

    # 锁单后复检，与手改竞争同一把 doc 锁。
    use_locks = _use_row_locks(db)
    locked = db.scalar(select(PrepDoc).where(PrepDoc.id == doc_id).with_for_update()) \
        if use_locks else doc
    if locked.status != "open":
        raise HTTPException(409, f"备料单已{('作废' if locked.status == 'voided' else '存档')}，不能作废")

    _release(locked, db, use_locks)
    locked.status = "voided"
    db.commit()
    db.refresh(locked)
    return _serialize_doc(locked, db)
