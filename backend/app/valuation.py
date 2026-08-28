"""Valuation in the context of a company's own history.

A P/E of 30 means nothing on its own. Thirty is cheap for a company that has
traded at forty for five years and expensive for one that has traded at
fifteen, and the number alone cannot tell you which. So every metric here is
reported three ways: what it is now, what this company's own median has been,
and where today sits inside that range.

That is the whole idea. "Is this cheap?" is unanswerable; "is this cheap for
this company?" is answerable from the company's own record.
"""

import asyncio
import statistics

from app.fmp_client import FMPError, _get, _pick

# Twenty quarters is five years, which is long enough to contain a full cycle
# for most businesses and short enough that the company is still recognisably
# the same one.
QUARTERS = 20

# The bar is drawn between these rather than the outright low and high. One
# quarter of a distorted multiple -- a loss-making quarter, a spike on an
# earnings gap -- would otherwise stretch the axis so far that every real
# observation crushes into a few pixels at one end.
BAR_LOW_PERCENTILE = 5
BAR_HIGH_PERCENTILE = 95


class Metric:
    """One row of the table, and where its numbers come from.

    `sources` are (payload key, field names) pairs, tried in order, because
    FMP has moved fields between its ratios and key-metrics endpoints and
    renamed them across API generations. Accepting several spellings is the
    difference between a blank row and a working one after a provider change.
    """

    def __init__(
        self,
        key: str,
        label: str,
        *,
        sources: list[tuple[str, tuple[str, ...]]],
        positive_only: bool = False,
        better: str | None = None,
        percent: bool = False,
    ):
        self.key = key
        self.label = label
        self.sources = sources
        # A negative P/E is not a cheap company, it is a loss-making one, and
        # letting one into a median produces a "typical valuation" that is
        # below zero. Excluded from the distribution rather than shown as a
        # bargain.
        self.positive_only = positive_only
        # Only set where the direction is genuinely unambiguous. A lower P/E
        # is not automatically better -- it is frequently a warning -- so the
        # valuation multiples deliberately have none.
        self.better = better
        self.percent = percent


METRICS: list[Metric] = [
    Metric(
        "peRatio",
        "P/E (trailing)",
        sources=[("ratios", ("priceToEarningsRatio", "priceEarningsRatio", "peRatio"))],
        positive_only=True,
    ),
    Metric("forwardPe", "P/E (forward)", sources=[], positive_only=True),
    Metric(
        "priceToSales",
        "P/S",
        sources=[("ratios", ("priceToSalesRatio", "priceSalesRatio"))],
        positive_only=True,
    ),
    Metric(
        "evToEbitda",
        "EV/EBITDA",
        sources=[("keyMetrics", ("evToEBITDA", "enterpriseValueOverEBITDA"))],
        positive_only=True,
    ),
    Metric(
        "evToSales",
        "EV/Sales",
        sources=[("keyMetrics", ("evToSales", "enterpriseValueOverRevenue"))],
        positive_only=True,
    ),
    Metric(
        "priceToFcf",
        "Price/FCF",
        sources=[
            ("ratios", ("priceToFreeCashFlowRatio", "priceToFreeCashFlowsRatio")),
            ("keyMetrics", ("priceToFreeCashFlowsRatio",)),
        ],
        positive_only=True,
    ),
    Metric(
        "grossMargin",
        "Gross margin",
        sources=[("ratios", ("grossProfitMargin", "grossProfitMarginRatio"))],
        better="high",
        percent=True,
    ),
    Metric(
        "operatingMargin",
        "Operating margin",
        sources=[("ratios", ("operatingProfitMargin", "operatingIncomeRatio"))],
        better="high",
        percent=True,
    ),
    Metric("revenueGrowth", "Revenue growth (YoY)", sources=[], better="high", percent=True),
    Metric("fcfMargin", "FCF margin", sources=[], better="high", percent=True),
    Metric(
        "netDebtToEbitda",
        "Net debt / EBITDA",
        sources=[("keyMetrics", ("netDebtToEBITDA", "netDebtToEbitda"))],
    ),
    Metric("shareChange", "Share count change (YoY)", sources=[], better="low", percent=True),
]

METRICS_BY_KEY = {m.key: m for m in METRICS}


def percentile(values: list[float], fraction: float) -> float | None:
    """Linear-interpolated percentile, so a short series still has a spread.

    `statistics.quantiles` needs at least two points and returns fixed cut
    points; this needs an arbitrary one from as few as one observation.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def percentile_rank(values: list[float], value: float) -> float | None:
    """Where `value` sits in `values`, 0 (lowest) to 1 (highest).

    Ties count as half, which keeps a flat series -- a margin that has not
    moved in five years -- reading as the middle rather than the top.
    """
    if not values:
        return None
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (below + equal / 2) / len(values)


def summarise(history: list[float | None], current: float | None, metric: Metric) -> dict:
    """One metric's current value against its own five-year record."""
    values = [v for v in history if isinstance(v, (int, float))]
    if metric.positive_only:
        values = [v for v in values if v > 0]
        if current is not None and current <= 0:
            current = None

    if not values:
        return {
            "value": current,
            "median": None,
            "low": None,
            "high": None,
            "percentile": None,
            "samples": 0,
        }

    return {
        "value": current,
        "median": statistics.median(values),
        # Trimmed, so one distorted quarter cannot flatten the whole axis.
        "low": percentile(values, BAR_LOW_PERCENTILE / 100),
        "high": percentile(values, BAR_HIGH_PERCENTILE / 100),
        "percentile": None if current is None else percentile_rank(values, current),
        "samples": len(values),
    }


def series_from(rows: list[dict], names: tuple[str, ...]) -> list[float | None]:
    """One field pulled out of a list of periods, newest first."""
    out: list[float | None] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _pick(row, *names)
        out.append(float(value) if isinstance(value, (int, float)) else None)
    return out


def year_over_year(rows: list[dict], names: tuple[str, ...]) -> list[float | None]:
    """A quarter against the same quarter a year earlier, as a fraction.

    Same quarter rather than the previous one: comparing a retailer's December
    to its September would report a seasonal swing as growth.
    """
    values = series_from(rows, names)
    out: list[float | None] = []
    for index, value in enumerate(values):
        year_ago = values[index + 4] if index + 4 < len(values) else None
        if value is None or year_ago is None or year_ago == 0:
            out.append(None)
            continue
        out.append((value - year_ago) / abs(year_ago))
    return out


def ratio_series(
    numerators: list[float | None], denominators: list[float | None]
) -> list[float | None]:
    out: list[float | None] = []
    for numerator, denominator in zip(numerators, denominators):
        if numerator is None or denominator in (None, 0):
            out.append(None)
        else:
            out.append(numerator / denominator)
    return out


def first_number(values: list[float | None]) -> float | None:
    """The most recent observation, skipping periods that reported nothing."""
    for value in values:
        if value is not None:
            return value
    return None


def build(payloads: dict, profile: dict, forward_pe: float | None) -> dict:
    """Assemble every metric from the raw endpoint payloads.

    Split out from fetching so the whole shape can be exercised against saved
    responses without a network -- which also means a provider changing a
    field name shows up as a failing test rather than an empty column.
    """
    ratios = payloads.get("ratios") or []
    key_metrics = payloads.get("keyMetrics") or []
    income = payloads.get("income") or []
    cash_flow = payloads.get("cashFlow") or []

    derived: dict[str, list[float | None]] = {
        "revenueGrowth": year_over_year(income, ("revenue", "totalRevenue")),
        "shareChange": year_over_year(
            income, ("weightedAverageShsOutDil", "weightedAverageShsOut")
        ),
        "fcfMargin": ratio_series(
            series_from(cash_flow, ("freeCashFlow",)),
            series_from(income, ("revenue", "totalRevenue")),
        ),
    }

    metrics: dict[str, dict] = {}
    for metric in METRICS:
        if metric.key in derived:
            history = derived[metric.key]
        else:
            history = []
            for payload_key, names in metric.sources:
                candidate = series_from(payloads.get(payload_key) or [], names)
                if any(v is not None for v in candidate):
                    history = candidate
                    break

        if metric.key == "forwardPe":
            # No history: a forward multiple is a view of the future, and the
            # forecasts behind past ones are not published anywhere. Shown as
            # a bare number, honestly without context.
            metrics[metric.key] = {
                "value": forward_pe,
                "median": None,
                "low": None,
                "high": None,
                "percentile": None,
                "samples": 0,
            }
            continue

        current = first_number(history)
        # The trailing series includes the current quarter, so ranking it
        # against a list containing itself is correct: it is one of the
        # twenty observations, not an outsider being placed among them.
        metrics[metric.key] = summarise(history, current, metric)

    return {
        "ticker": profile.get("symbol", ""),
        "companyName": profile.get("companyName"),
        "sector": profile.get("sector"),
        "price": profile.get("price"),
        "metrics": metrics,
        "error": None,
    }


async def fetch_valuation(ticker: str) -> dict:
    """Five years of quarterly fundamentals for one company."""
    from app.config import settings

    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is not set")

    import httpx

    ticker = ticker.strip().upper()
    limit = str(QUARTERS)

    async with httpx.AsyncClient(timeout=25) as client:
        profile, ratios, key_metrics, income, cash_flow, estimates = await asyncio.gather(
            _get(client, "profile", symbol=ticker),
            _get(client, "ratios", symbol=ticker, period="quarter", limit=limit),
            _get(client, "key-metrics", symbol=ticker, period="quarter", limit=limit),
            _get(client, "income-statement", symbol=ticker, period="quarter", limit=limit),
            _get(client, "cash-flow-statement", symbol=ticker, period="quarter", limit=limit),
            # Forward earnings are the one thing that cannot be derived from
            # the record, and the one call most likely to be outside a free
            # plan. It fails on its own so the other eleven rows survive it.
            _get(client, "analyst-estimates", symbol=ticker, period="annual", limit="1"),
            return_exceptions=True,
        )

    if isinstance(profile, Exception):
        raise profile

    payloads = {
        "ratios": _rows(ratios),
        "keyMetrics": _rows(key_metrics),
        "income": _rows(income),
        "cashFlow": _rows(cash_flow),
    }
    first_profile = _rows(profile)
    if not first_profile:
        raise FMPError(f"No data found for ticker '{ticker}'")

    return build(payloads, first_profile[0], _forward_pe(first_profile[0], _rows(estimates)))


def _rows(payload) -> list[dict]:
    if isinstance(payload, Exception) or payload is None:
        return []
    if isinstance(payload, dict):
        return [payload]
    return [row for row in payload if isinstance(row, dict)]


def _forward_pe(profile: dict, estimates: list[dict]) -> float | None:
    """Price divided by next year's consensus earnings per share."""
    price = _pick(profile, "price")
    if not isinstance(price, (int, float)) or not estimates:
        return None

    eps = _pick(estimates[0], "epsAvg", "estimatedEpsAvg", "eps")
    if not isinstance(eps, (int, float)) or eps <= 0:
        return None
    return price / eps
