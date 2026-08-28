"""Valuation in the context of a company's own history.

The arithmetic is tested against saved payloads rather than the live API,
which this environment cannot reach. That is also the point of splitting
`build` from the fetching: a provider renaming a field shows up here as a
column that went blank, rather than in production as a table of dashes.
"""

import pytest
from fastapi.testclient import TestClient

from app import db, valuation
from app.fmp_client import FMPError
from app.main import app
from app.routers import valuation as valuation_router


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def quarters(**series) -> list[dict]:
    """Rows newest-first, the way FMP returns them."""
    length = max(len(v) for v in series.values())
    return [{k: v[i] if i < len(v) else None for k, v in series.items()} for i in range(length)]


class TestPercentiles:
    def test_a_single_observation_is_its_own_percentile(self, client):
        assert valuation.percentile([42.0], 0.5) == 42.0

    def test_the_median_of_an_even_series_interpolates(self):
        assert valuation.percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 25.0

    def test_an_empty_series_has_none(self):
        assert valuation.percentile([], 0.5) is None
        assert valuation.percentile_rank([], 1.0) is None

    def test_the_lowest_value_ranks_at_the_bottom(self):
        assert valuation.percentile_rank([10.0, 20.0, 30.0], 5.0) == 0.0

    def test_the_highest_value_ranks_at_the_top(self):
        assert valuation.percentile_rank([10.0, 20.0, 30.0], 40.0) == 1.0

    def test_a_flat_series_reads_as_the_middle_not_the_top(self):
        # A margin that has not moved in five years is neither high nor low
        # for the company. Counting ties as whole would put it at 100%.
        assert valuation.percentile_rank([15.0, 15.0, 15.0], 15.0) == 0.5


class TestDistribution:
    def test_a_loss_making_quarter_is_not_a_cheap_valuation(self):
        # A negative P/E is a company losing money, not a bargain. Left in,
        # the median "typical valuation" comes out below zero.
        metric = valuation.METRICS_BY_KEY["peRatio"]
        summary = valuation.summarise([30.0, 28.0, -12.0, 32.0], 30.0, metric)
        assert summary["samples"] == 3
        assert summary["median"] == 30.0

    def test_a_company_currently_at_a_loss_shows_no_multiple(self):
        metric = valuation.METRICS_BY_KEY["peRatio"]
        assert valuation.summarise([30.0, 28.0], -5.0, metric)["value"] is None

    def test_a_negative_margin_is_kept_because_it_is_real(self):
        # Unlike a multiple, a margin below zero is a fact about the business
        # and belongs in its range.
        metric = valuation.METRICS_BY_KEY["operatingMargin"]
        assert valuation.summarise([-0.05, 0.1, 0.2], -0.05, metric)["samples"] == 3

    def test_the_bar_is_trimmed_so_one_spike_cannot_flatten_it(self):
        # An earnings gap can leave a single quarter at ten times the normal
        # multiple. Drawn to the outright high, every real observation would
        # crush into the left tenth of the bar.
        metric = valuation.METRICS_BY_KEY["priceToSales"]
        history = [5.0] * 19 + [400.0]
        summary = valuation.summarise(history, 5.0, metric)
        assert summary["high"] < 100
        assert summary["median"] == 5.0

    def test_a_metric_with_no_history_still_reports_today(self):
        metric = valuation.METRICS_BY_KEY["priceToSales"]
        summary = valuation.summarise([], 4.2, metric)
        assert summary["value"] == 4.2
        assert summary["median"] is None
        assert summary["samples"] == 0


class TestYearOverYear:
    def test_growth_compares_the_same_quarter_a_year_earlier(self):
        # Comparing December to September would report a retailer's season
        # as growth.
        rows = quarters(revenue=[120, 100, 90, 80, 100])
        assert valuation.year_over_year(rows, ("revenue",))[0] == pytest.approx(0.2)

    def test_a_quarter_without_a_year_of_history_has_no_growth(self):
        rows = quarters(revenue=[120, 100])
        assert valuation.year_over_year(rows, ("revenue",)) == [None, None]

    def test_growth_from_a_negative_base_keeps_its_sign(self):
        # Dividing by a negative denominator would flip a recovery into a
        # reported decline.
        rows = quarters(revenue=[50, 0, 0, 0, -100])
        assert valuation.year_over_year(rows, ("revenue",))[0] == pytest.approx(1.5)

    def test_a_zero_base_is_skipped_rather_than_dividing(self):
        rows = quarters(revenue=[50, 0, 0, 0, 0])
        assert valuation.year_over_year(rows, ("revenue",))[0] is None


class TestBuildingTheSnapshot:
    def payloads(self):
        return {
            "ratios": quarters(
                priceToEarningsRatio=[32.0, 28.0, 24.0, 20.0, 18.0],
                priceToSalesRatio=[8.0, 7.0, 6.0, 5.0, 5.0],
                grossProfitMargin=[0.46, 0.45, 0.44, 0.43, 0.43],
                operatingProfitMargin=[0.31, 0.30, 0.29, 0.28, 0.28],
            ),
            "keyMetrics": quarters(
                evToEBITDA=[24.0, 22.0, 20.0, 18.0, 17.0],
                evToSales=[7.8, 6.9, 5.9, 4.9, 4.9],
                netDebtToEBITDA=[0.4, 0.5, 0.6, 0.7, 0.8],
            ),
            "income": quarters(
                revenue=[120, 110, 105, 100, 100],
                weightedAverageShsOutDil=[98, 99, 100, 100, 100],
            ),
            "cashFlow": quarters(freeCashFlow=[36, 33, 30, 28, 25]),
        }

    def test_every_metric_is_present_even_when_a_source_is_missing(self):
        built = valuation.build({}, {"symbol": "AAPL"}, None)
        assert set(built["metrics"]) == {m.key for m in valuation.METRICS}
        assert all(m["value"] is None for m in built["metrics"].values())

    def test_the_current_value_is_the_most_recent_quarter(self):
        built = valuation.build(self.payloads(), {"symbol": "AAPL"}, None)
        assert built["metrics"]["peRatio"]["value"] == 32.0

    def test_todays_multiple_is_ranked_against_its_own_five_years(self):
        # The question the table exists to answer: expensive for this
        # company, or merely expensive-looking.
        built = valuation.build(self.payloads(), {"symbol": "AAPL"}, None)
        pe = built["metrics"]["peRatio"]
        assert pe["median"] == 24.0
        assert pe["percentile"] == pytest.approx(0.9)

    def test_a_buyback_reads_as_a_shrinking_share_count(self):
        # Dilution matters, and it is invisible in every other row here.
        built = valuation.build(self.payloads(), {"symbol": "AAPL"}, None)
        assert built["metrics"]["shareChange"]["value"] == pytest.approx(-0.02)

    def test_fcf_margin_is_cash_flow_over_revenue_of_the_same_quarter(self):
        built = valuation.build(self.payloads(), {"symbol": "AAPL"}, None)
        assert built["metrics"]["fcfMargin"]["value"] == pytest.approx(0.3)

    def test_a_renamed_field_is_still_found(self):
        # FMP has moved and renamed these across API generations; accepting
        # the known spellings is the difference between a working row and a
        # blank one after a provider change.
        payloads = {"ratios": quarters(priceEarningsRatio=[19.0, 18.0])}
        built = valuation.build(payloads, {"symbol": "AAPL"}, None)
        assert built["metrics"]["peRatio"]["value"] == 19.0

    def test_forward_earnings_are_shown_without_a_range(self):
        # Nobody publishes what the forecasts behind past forward multiples
        # were, so there is no history to rank one against.
        built = valuation.build(self.payloads(), {"symbol": "AAPL"}, 26.5)
        assert built["metrics"]["forwardPe"]["value"] == 26.5
        assert built["metrics"]["forwardPe"]["median"] is None

    def test_a_gap_in_the_latest_quarter_falls_back_to_the_one_before(self):
        payloads = {"ratios": quarters(priceToEarningsRatio=[None, 28.0, 24.0])}
        built = valuation.build(payloads, {"symbol": "AAPL"}, None)
        assert built["metrics"]["peRatio"]["value"] == 28.0


class TestForwardPe:
    def test_is_price_over_next_years_consensus(self):
        assert valuation._forward_pe({"price": 265.0}, [{"epsAvg": 10.0}]) == 26.5

    def test_is_absent_when_the_estimate_is_a_loss(self):
        assert valuation._forward_pe({"price": 265.0}, [{"epsAvg": -1.0}]) is None

    def test_is_absent_when_estimates_could_not_be_fetched(self):
        # The call most likely to sit outside a free plan, so it fails on its
        # own without taking the other rows with it.
        assert valuation._forward_pe({"price": 265.0}, []) is None


class TestTheEndpoint:
    def stub(self, monkeypatch, result=None, error=None):
        async def fetch(ticker):
            if error:
                raise error
            return {**result, "ticker": ticker}

        monkeypatch.setattr(valuation_router, "fetch_valuation", fetch)

    def snapshot(self, pe=30.0):
        return {
            "ticker": "",
            "companyName": "Test Co",
            "sector": "Technology",
            "price": 100.0,
            "metrics": {
                m.key: {
                    "value": pe if m.key == "peRatio" else None,
                    "median": None,
                    "low": None,
                    "high": None,
                    "percentile": None,
                    "samples": 0,
                }
                for m in valuation.METRICS
            },
            "error": None,
        }

    def test_an_empty_comparison_list_returns_no_companies(self, client):
        body = client.get("/api/valuation").json()
        assert body["companies"] == []
        assert [m["key"] for m in body["metrics"]] == [m.key for m in valuation.METRICS]

    def test_a_company_in_the_list_is_priced(self, client, monkeypatch):
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        self.stub(monkeypatch, self.snapshot())
        body = client.get("/api/valuation").json()
        assert [c["ticker"] for c in body["companies"]] == ["AAPL"]

    def test_the_peer_median_is_the_middle_of_what_is_on_screen(self, client, monkeypatch):
        # A 34x multiple reads differently when the others are at 12 than
        # when they are at 40, so every number gets a reference point.
        for ticker in ("AAPL", "MSFT", "NVDA"):
            db.add_to_watchlist(ticker, db.DEFAULT_OWNER, db.COMPARE_LIST)

        prices = {"AAPL": 10.0, "MSFT": 20.0, "NVDA": 60.0}

        async def fetch(ticker):
            return {**self.snapshot(prices[ticker]), "ticker": ticker}

        monkeypatch.setattr(valuation_router, "fetch_valuation", fetch)
        assert client.get("/api/valuation").json()["peerMedian"]["peRatio"] == 20.0

    def test_a_metric_nobody_reported_has_no_peer_median(self, client, monkeypatch):
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        self.stub(monkeypatch, self.snapshot())
        assert client.get("/api/valuation").json()["peerMedian"]["evToSales"] is None

    def test_the_second_call_is_served_from_cache(self, client, monkeypatch):
        # Six calls per company against 250 a day: uncached, a table of five
        # would exhaust a free plan by lunchtime.
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        calls = []

        async def fetch(ticker):
            calls.append(ticker)
            return {**self.snapshot(), "ticker": ticker}

        monkeypatch.setattr(valuation_router, "fetch_valuation", fetch)
        client.get("/api/valuation")
        client.get("/api/valuation")
        assert calls == ["AAPL"]

    def test_refresh_goes_back_to_the_provider(self, client, monkeypatch):
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        calls = []

        async def fetch(ticker):
            calls.append(ticker)
            return {**self.snapshot(), "ticker": ticker}

        monkeypatch.setattr(valuation_router, "fetch_valuation", fetch)
        client.get("/api/valuation")
        client.get("/api/valuation?refresh=true")
        assert len(calls) == 2

    def test_a_day_old_table_beats_an_error_message(self, client, monkeypatch):
        # The common case on a free plan: the quota is spent and the numbers
        # have not moved anyway.
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        self.stub(monkeypatch, self.snapshot(30.0))
        client.get("/api/valuation")

        self.stub(monkeypatch, error=FMPError("rate limit reached"))
        company = client.get("/api/valuation?refresh=true").json()["companies"][0]

        assert company["metrics"]["peRatio"]["value"] == 30.0
        assert company["stale"] is True
        assert "rate limit" in company["error"]

    def test_a_failure_with_nothing_cached_names_the_company(self, client, monkeypatch):
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        self.stub(monkeypatch, error=FMPError("rate limit reached"))
        company = client.get("/api/valuation").json()["companies"][0]
        assert company["ticker"] == "AAPL"
        assert "rate limit" in company["error"]

    def test_one_company_failing_does_not_take_the_table_down(self, client, monkeypatch):
        for ticker in ("AAPL", "MSFT"):
            db.add_to_watchlist(ticker, db.DEFAULT_OWNER, db.COMPARE_LIST)

        async def fetch(ticker):
            if ticker == "MSFT":
                raise FMPError("no data")
            return {**self.snapshot(), "ticker": ticker}

        monkeypatch.setattr(valuation_router, "fetch_valuation", fetch)
        companies = client.get("/api/valuation").json()["companies"]
        assert [c["ticker"] for c in companies] == ["AAPL", "MSFT"]
        assert companies[0]["error"] is None
        assert companies[1]["error"] == "no data"

    def test_only_margins_growth_and_dilution_claim_a_direction(self, client):
        # A lower P/E is not automatically better -- frequently it is a
        # warning -- so highlighting a "winner" there would be a judgement
        # the data does not support.
        defs = {m["key"]: m["better"] for m in client.get("/api/valuation").json()["metrics"]}
        assert defs["grossMargin"] == "high"
        assert defs["revenueGrowth"] == "high"
        assert defs["shareChange"] == "low"
        for key in ("peRatio", "priceToSales", "evToEbitda", "priceToFcf", "netDebtToEbitda"):
            assert defs[key] is None
