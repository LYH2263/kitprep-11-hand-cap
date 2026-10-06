"""手改备料单的事务口径：数量与占用同变同停，超需求整单退回，作废/存档只读，存档快照不改字。"""
from sqlalchemy import select

from app.models.models import Ingredient, PrepDoc, PrepLine, PrepRun


def _gen(client):
    client.post("/api/prep/run?order_id=1")
    return client.get("/api/prep/docs/active?order_id=1").json()


def _ing(db, code):
    return db.scalar(select(Ingredient).where(Ingredient.code == code))


def test_run_creates_doc_with_reservation(client, db_session):
    doc = _gen(client)
    assert doc["status"] == "open"
    pork = next(l for l in doc["lines"] if l["ingredient_code"] == "I-PR")
    # 生成即占用：需求 = 数量 = 占用（五花肉 40*0.25 = 10）
    assert (pork["need_qty"], pork["qty"], pork["reserved_qty"]) == (10.0, 10.0, 10.0)
    db_session.expire_all()
    assert _ing(db_session, "I-PR").reserved_qty == 10.0


def test_edit_down_moves_qty_and_reservation_together(client, db_session):
    doc = _gen(client)
    pork = next(l for l in doc["lines"] if l["ingredient_code"] == "I-PR")

    r = client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 6})
    assert r.status_code == 200
    line = next(l for l in r.json()["lines"] if l["id"] == pork["id"])
    assert (line["qty"], line["reserved_qty"]) == (6.0, 6.0)

    # 库存占用同步减 4：10 -> 6
    db_session.expire_all()
    assert _ing(db_session, "I-PR").reserved_qty == 6.0
    # 其他行原样
    rice = next(l for l in r.json()["lines"] if l["ingredient_code"] == "I-RC")
    assert rice["qty"] == rice["need_qty"] == 10.5


def test_edit_above_need_fails_atomically(client, db_session):
    doc = _gen(client)
    pork = next(l for l in doc["lines"] if l["ingredient_code"] == "I-PR")

    # 先合法减量到 6
    assert client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 6}).status_code == 200
    # 再越过需求上限（10）→ 整单失败退回
    r = client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 10.5})
    assert r.status_code == 422

    # 行数量/占用停在 6，库存占用也没被推动
    db_session.expire_all()
    line = db_session.get(PrepLine, pork["id"])
    assert (line.qty, line.reserved_qty) == (6.0, 6.0)
    assert _ing(db_session, "I-PR").reserved_qty == 6.0


def test_edit_up_within_need_restores_reservation(client, db_session):
    doc = _gen(client)
    pork = next(l for l in doc["lines"] if l["ingredient_code"] == "I-PR")
    client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 4})
    r = client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 9})
    assert r.status_code == 200
    db_session.expire_all()
    assert _ing(db_session, "I-PR").reserved_qty == 9.0


def test_negative_qty_rejected(client, db_session):
    doc = _gen(client)
    pork = next(l for l in doc["lines"] if l["ingredient_code"] == "I-PR")
    r = client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": -1})
    assert r.status_code == 422
    db_session.expire_all()
    line = db_session.get(PrepLine, pork["id"])
    assert line.qty == 10.0
    assert _ing(db_session, "I-PR").reserved_qty == 10.0


def test_zero_and_exact_need_allowed(client, db_session):
    doc = _gen(client)
    pork = next(l for l in doc["lines"] if l["ingredient_code"] == "I-PR")
    assert client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 0}).status_code == 200
    db_session.expire_all()
    assert _ing(db_session, "I-PR").reserved_qty == 0.0
    assert client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 10}).status_code == 200
    db_session.expire_all()
    assert _ing(db_session, "I-PR").reserved_qty == 10.0


def test_voided_doc_cannot_be_edited(client, db_session):
    doc = _gen(client)
    pork = next(l for l in doc["lines"] if l["ingredient_code"] == "I-PR")
    assert client.post(f"/api/prep/docs/{doc['id']}/void").status_code == 200

    # 作废释放占用
    db_session.expire_all()
    assert _ing(db_session, "I-PR").reserved_qty == 0.0

    r = client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 5})
    assert r.status_code == 409
    db_session.expire_all()
    line = db_session.get(PrepLine, pork["id"])
    assert line.qty == 10.0  # 没动


def test_archived_doc_is_frozen(client, db_session):
    first = _gen(client)
    _gen(client)  # 再次生成：旧 open 单应存档并释放占用

    db_session.expire_all()
    old = db_session.get(PrepDoc, first["id"])
    assert old.status == "archived"
    assert _ing(db_session, "I-PR").reserved_qty == 10.0  # 只挂新单一份，不重复占用

    line = next(l for l in first["lines"] if l["ingredient_code"] == "I-PR")
    r = client.post(f"/api/prep/docs/{old.id}/lines/{line['id']}", json={"qty": 1})
    assert r.status_code == 409
    db_session.expire_all()
    assert db_session.get(PrepLine, line["id"]).qty == 10.0  # 更早存档单没被改字


def test_missing_line_writes_nothing(client, db_session):
    doc = _gen(client)
    # 不存在的行
    r = client.post(f"/api/prep/docs/{doc['id']}/lines/99999", json={"qty": 1})
    assert r.status_code == 404
    # 别的单据的行不能挂到这张单上
    _gen(client)  # 旧单存档，拿到新 active
    active = client.get("/api/prep/docs/active?order_id=1").json()
    archived_line = doc["lines"][0]["id"]
    r = client.post(f"/api/prep/docs/{active['id']}/lines/{archived_line}", json={"qty": 1})
    assert r.status_code == 404
    db_session.expire_all()
    assert db_session.get(PrepLine, archived_line).qty == 10.0


def test_snapshot_run_json_not_modified_by_edit(client, db_session):
    doc = _gen(client)
    pork = next(l for l in doc["lines"] if l["ingredient_code"] == "I-PR")
    client.post(f"/api/prep/docs/{doc['id']}/lines/{pork['id']}", json={"qty": 2})

    # PrepRun 存档快照仍是原始需求
    latest = client.get("/api/prep/latest?order_id=1").json()
    snap_pork = next(l for l in latest["prep_lines"] if l["ingredient_code"] == "I-PR")
    assert snap_pork["need_qty"] == 10.0

    run = db_session.scalar(select(PrepRun).where(PrepRun.id == doc["prep_run_id"]))
    assert '"need_qty": 10.0' in run.result_json


def test_reserved_equals_sum_of_open_lines(client, db_session):
    doc = _gen(client)
    lines = {l["ingredient_code"]: l for l in doc["lines"]}
    client.post(f"/api/prep/docs/{doc['id']}/lines/{lines['I-PR']['id']}", json={"qty": 3})
    client.post(f"/api/prep/docs/{doc['id']}/lines/{lines['I-RC']['id']}", json={"qty": 7})

    db_session.expire_all()
    open_lines = db_session.scalars(
        select(PrepLine).join(PrepDoc).where(PrepDoc.status == "open")
    ).all()
    for ing in db_session.scalars(select(Ingredient)).all():
        expect = round(sum(l.reserved_qty for l in open_lines if l.ingredient_id == ing.id), 3)
        assert round(ing.reserved_qty, 3) == expect
