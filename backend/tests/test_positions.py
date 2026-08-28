"""Lots, splits, and the ways they can go wrong.

The arithmetic on top of these lots lives in the frontend, where the prices
are; what is tested here is that the lots themselves survive intact -- through
a sign-in, a split, and a mistyped split.
"""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def lots(response) -> list[dict]:
    return response.json()["lots"]


class TestRecordingLots:
    def test_a_purchase_comes_back_with_what_was_paid(self, client):
        client.post(
            "/api/positions/AAPL/lots",
            json={"shares": 10, "costPerShare": 142.3, "tradeDate": "2025-03-04"},
        )
        held = lots(client.get("/api/positions"))
        assert len(held) == 1
        assert held[0]["ticker"] == "AAPL"
        assert held[0]["shares"] == 10
        assert held[0]["costPerShare"] == 142.3

    def test_adding_to_a_position_keeps_both_lots(self, client):
        # The whole reason for a list rather than a number: a second buy must
        # not overwrite what the first one cost.
        for shares, price in ((10, 100.0), (5, 200.0)):
            client.post(
                "/api/positions/AAPL/lots",
                json={"shares": shares, "costPerShare": price, "tradeDate": "2025-03-04"},
            )
        assert [l["costPerShare"] for l in lots(client.get("/api/positions"))] == [100.0, 200.0]

    def test_a_sale_is_a_lot_with_negative_shares(self, client):
        client.post(
            "/api/positions/AAPL/lots",
            json={"shares": -4, "costPerShare": 180.0, "tradeDate": "2025-06-01"},
        )
        assert lots(client.get("/api/positions"))[0]["shares"] == -4

    def test_lots_come_back_in_the_order_they_happened(self, client):
        # Average cost is walked in trade order, so a sale is priced against
        # the basis as it stood then. Entering trades out of order is normal.
        for date in ("2025-06-01", "2025-01-01", "2025-03-01"):
            client.post(
                "/api/positions/AAPL/lots",
                json={"shares": 1, "costPerShare": 100.0, "tradeDate": date},
            )
        dates = [l["tradeDate"] for l in lots(client.get("/api/positions"))]
        assert dates == sorted(dates)

    def test_ticker_case_and_padding_are_normalised(self, client):
        client.post(
            "/api/positions/  aapl  /lots",
            json={"shares": 1, "costPerShare": 100.0, "tradeDate": "2025-01-01"},
        )
        assert lots(client.get("/api/positions"))[0]["ticker"] == "AAPL"

    def test_zero_shares_is_refused(self, client):
        r = client.post(
            "/api/positions/AAPL/lots",
            json={"shares": 0, "costPerShare": 100.0, "tradeDate": "2025-01-01"},
        )
        assert r.status_code == 400

    def test_a_blank_price_is_refused_rather_than_read_as_free(self, client):
        # Zero cost would report the entire position as profit.
        r = client.post(
            "/api/positions/AAPL/lots",
            json={"shares": 10, "costPerShare": 0, "tradeDate": "2025-01-01"},
        )
        assert r.status_code == 400
        assert "price per share" in r.json()["detail"]

    def test_deleting_a_lot_leaves_the_others(self, client):
        client.post(
            "/api/positions/AAPL/lots",
            json={"shares": 10, "costPerShare": 100.0, "tradeDate": "2025-01-01"},
        )
        client.post(
            "/api/positions/MSFT/lots",
            json={"shares": 3, "costPerShare": 400.0, "tradeDate": "2025-01-01"},
        )
        first = lots(client.get("/api/positions"))[0]
        remaining = lots(client.delete(f"/api/positions/lots/{first['id']}"))
        assert [l["ticker"] for l in remaining] == ["MSFT"]


class TestSplits:
    def setup_position(self, client):
        client.post(
            "/api/positions/AAPL/lots",
            json={"shares": 10, "costPerShare": 400.0, "tradeDate": "2025-01-01"},
        )

    def test_a_four_for_one_leaves_the_money_invested_unchanged(self, client):
        self.setup_position(client)
        body = client.post("/api/positions/AAPL/split", json={"ratio": 4}).json()
        lot = body["lots"][0]
        assert lot["shares"] == 40
        assert lot["costPerShare"] == 100.0
        assert lot["shares"] * lot["costPerShare"] == 4000.0

    def test_a_reverse_split_works_the_same_way(self, client):
        self.setup_position(client)
        lot = client.post("/api/positions/AAPL/split", json={"ratio": 0.1}).json()["lots"][0]
        assert lot["shares"] == 1
        assert lot["costPerShare"] == 4000.0

    def test_only_the_split_ticker_is_touched(self, client):
        self.setup_position(client)
        client.post(
            "/api/positions/MSFT/lots",
            json={"shares": 5, "costPerShare": 200.0, "tradeDate": "2025-01-01"},
        )
        after = {l["ticker"]: l for l in client.post("/api/positions/AAPL/split", json={"ratio": 2}).json()["lots"]}
        assert after["MSFT"]["shares"] == 5
        assert after["MSFT"]["costPerShare"] == 200.0

    def test_undoing_restores_the_original_figures_exactly(self, client):
        # The reason splits are recorded at all: a ratio typed as 10 instead
        # of 0.1 wrecks every basis, and re-entering lots from memory is not
        # a recovery.
        self.setup_position(client)
        body = client.post("/api/positions/AAPL/split", json={"ratio": 10}).json()
        restored = client.delete(f"/api/positions/splits/{body['splits'][0]['id']}").json()
        assert restored["lots"][0]["shares"] == 10
        assert restored["lots"][0]["costPerShare"] == 400.0
        assert restored["splits"] == []

    def test_an_applied_split_is_listed_so_it_can_be_undone(self, client):
        self.setup_position(client)
        splits = client.post("/api/positions/AAPL/split", json={"ratio": 4}).json()["splits"]
        assert splits[0]["ticker"] == "AAPL"
        assert splits[0]["ratio"] == 4

    @pytest.mark.parametrize("ratio", [0, -2, 5000])
    def test_an_impossible_ratio_is_refused(self, client, ratio):
        self.setup_position(client)
        assert client.post("/api/positions/AAPL/split", json={"ratio": ratio}).status_code == 400

    def test_splitting_a_ticker_you_hold_nothing_of_is_refused(self, client):
        # Silently recording it would restate a future lot that predates
        # nothing, quietly halving a basis entered later.
        r = client.post("/api/positions/TSLA/split", json={"ratio": 4})
        assert r.status_code == 400
        assert "no lots recorded" in r.json()["detail"]

    def test_undoing_a_split_that_is_already_gone_says_so(self, client):
        assert client.delete("/api/positions/splits/nope").status_code == 404


class TestOwnership:
    def test_lots_are_private_to_their_owner(self, client):
        db.add_lot("space:someone-else", "AAPL", 10, 100.0, "2025-01-01")
        assert lots(client.get("/api/positions")) == []

    def test_another_owners_lot_cannot_be_deleted(self, client):
        other = db.add_lot("space:someone-else", "AAPL", 10, 100.0, "2025-01-01")
        client.delete(f"/api/positions/lots/{other['id']}")
        assert db.list_lots("space:someone-else") != []

    def test_signing_in_carries_positions_onto_the_account(self, client):
        # A position entered before signing in is real money; losing it at the
        # moment of sign-in would be the worst possible time.
        db.add_lot("space:browser", "AAPL", 10, 100.0, "2025-01-01")
        db.apply_split("space:browser", "AAPL", 4)

        moved = db.transfer_owner("space:browser", "user:alice")

        assert moved["lots"] == 1
        assert db.list_lots("space:browser") == []
        carried = db.list_lots("user:alice")
        assert carried[0]["shares"] == 40
        assert [s["ticker"] for s in db.list_splits("user:alice")] == ["AAPL"]

    def test_two_identical_trades_both_survive_a_sign_in(self, client):
        # Watchlist rows de-duplicate on merge; lots must not. Buying the same
        # amount of the same stock twice is a real thing people do.
        for _ in range(2):
            db.add_lot("space:browser", "AAPL", 10, 100.0, "2025-01-01")
        db.transfer_owner("space:browser", "user:alice")
        assert len(db.list_lots("user:alice")) == 2
