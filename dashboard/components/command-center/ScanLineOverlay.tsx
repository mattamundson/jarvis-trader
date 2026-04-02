export function ScanLineOverlay() {
  return (
    <div
      className="fixed inset-0 z-[1] pointer-events-none"
      style={{
        background:
          "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px)",
      }}
    />
  );
}
