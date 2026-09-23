export function isPublicReadOnlyPath(pathname: string): boolean {
  return (
    pathname === "/market-brief-public" ||
    pathname.startsWith("/market-brief-public/") ||
    pathname === "/api/public-market-brief/latest" ||
    pathname.startsWith("/api/public-market-brief/latest/")
  );
}
