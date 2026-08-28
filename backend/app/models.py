from pydantic import BaseModel


class TickerRequest(BaseModel):
    ticker: str


class NoteRequest(BaseModel):
    note: str | None = None


class FundamentalsRow(BaseModel):
    ticker: str
    companyName: str | None = None
    sector: str | None = None
    industry: str | None = None
    price: float | None = None
    marketCap: float | None = None
    beta: float | None = None
    peRatio: float | None = None
    pegRatio: float | None = None
    evToEbitda: float | None = None
    priceToBook: float | None = None
    priceToSales: float | None = None
    debtToEquity: float | None = None
    currentRatio: float | None = None
    revenueGrowth: float | None = None
    epsGrowth: float | None = None
    netProfitMargin: float | None = None
    operatingMargin: float | None = None
    returnOnEquity: float | None = None
    dividendYield: float | None = None
    stale: bool = False
    fetchedAt: str | None = None
    error: str | None = None


class FedStatement(BaseModel):
    id: str
    date: str
    title: str
    url: str
    summary: str | None = None
    sentiment: str | None = None
    key_takeaways: list[str] = []
    fetched_at: str


class LotRequest(BaseModel):
    """One purchase or sale.

    Negative shares record a sale, with costPerShare carrying the price sold
    at. One shape serves both so a position's history stays a single ordered
    list rather than two that have to be interleaved to compute anything.
    """

    shares: float
    costPerShare: float
    tradeDate: str
    note: str | None = None


class SplitRequest(BaseModel):
    """A share split, as the multiple of new shares per old one.

    4-for-1 is 4. A reverse 1-for-10 is 0.1.
    """

    ratio: float


class JournalRequest(BaseModel):
    """A dated opinion about a company.

    `priceAtWrite` is optional because the page usually already holds the
    price the reader was looking at, which is the honest snapshot. Left out,
    the server fetches one.
    """

    body: str
    tags: list[str] = []
    priceAtWrite: float | None = None
