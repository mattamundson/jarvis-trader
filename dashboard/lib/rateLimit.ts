// Simple in-memory rate limiter
// For production, consider Vercel Edge Config or Upstash Redis
const requests = new Map<string, number[]>();

export function rateLimit(
  ip: string, 
  maxRequests: number = 60, 
  windowMs: number = 60000
): boolean {
  const now = Date.now();
  const userRequests = requests.get(ip) || [];
  
  // Clean old requests outside window
  const recentRequests = userRequests.filter(time => now - time < windowMs);
  
  if (recentRequests.length >= maxRequests) {
    return false; // Rate limited
  }
  
  recentRequests.push(now);
  requests.set(ip, recentRequests);
  return true; // Allowed
}

// Cleanup old entries periodically to prevent memory leak
setInterval(() => {
  const now = Date.now();
  const windowMs = 60000;
  
  for (const [ip, times] of requests.entries()) {
    const recentRequests = times.filter(time => now - time < windowMs);
    
    if (recentRequests.length === 0) {
      requests.delete(ip);
    } else {
      requests.set(ip, recentRequests);
    }
  }
}, 60000); // Cleanup every minute
