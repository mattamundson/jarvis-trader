interface BookLine {
  symbol: string;
  quantity: number;
}

/** Compare total quantities per symbol; duplicate rows must not hide a mismatch. */
export function bookDisagreements(portfolio: BookLine[], paper: BookLine[]): string[] {
  function totals(rows: BookLine[]): Map<string, number> {
    const result = new Map<string, number>();
    for (const row of rows) {
      result.set(row.symbol, (result.get(row.symbol) ?? 0) + row.quantity);
    }
    return result;
  }
  const left = totals(portfolio);
  const right = totals(paper);
  return [...new Set([...left.keys(), ...right.keys()])].sort().flatMap((symbol) => {
    const a = left.get(symbol) ?? 0;
    const b = right.get(symbol) ?? 0;
    if (!Number.isFinite(a) || !Number.isFinite(b)) {
      return [`${symbol}: quantity unavailable`];
    }
    return a === b ? [] : [`${symbol}: /portfolio qty ${a}; paper qty ${b}`];
  });
}
