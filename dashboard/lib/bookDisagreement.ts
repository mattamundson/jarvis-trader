export interface BookLine {
  symbol: string;
  quantity: number;
}

function totals(rows: BookLine[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const row of rows) {
    const symbol = row.symbol.trim().toUpperCase();
    if (!symbol) continue;
    const qty = Number(row.quantity);
    if (!Number.isFinite(qty)) continue;
    map.set(symbol, (map.get(symbol) ?? 0) + qty);
  }
  return map;
}

/**
 * Compare the in-memory /portfolio book with the DB-backed paper book.
 * Messages name the symbol and quantity only.
 */
export function bookDisagreements(portfolio: BookLine[], paper: BookLine[]): string[] {
  const left = totals(portfolio);
  const right = totals(paper);
  const symbols = new Set([...left.keys(), ...right.keys()]);
  const messages: string[] = [];
  for (const symbol of [...symbols].sort()) {
    const portfolioQty = left.get(symbol) ?? 0;
    const paperQty = right.get(symbol) ?? 0;
    if (portfolioQty === paperQty) continue;
    messages.push(
      `${symbol} quantity ${portfolioQty} on /portfolio and ${paperQty} on /portfolio/paper/positions`,
    );
  }
  return messages;
}
