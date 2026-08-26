from pydantic import BaseModel


class TickerRequest(BaseModel):
    ticker: str


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
