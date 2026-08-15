import datetime
import json
import sys

def is_market_open(dt):
    # US market hours: 9:30 AM - 4:00 PM ET, Monday-Friday
    market_open = datetime.time(9, 30)  # 9:30 AM
    market_close = datetime.time(16, 0)  # 4:00 PM
    day = dt.weekday()  # Monday=0, Sunday=6
    
    # Check if it's a weekday and within market hours
    if day < 5:  # Monday-Friday
        current_time = dt.time()
        if market_open <= current_time <= market_close:
            return True
    return False

def get_market_status():
    # Get current market status
    now = datetime.datetime.now()
    market_open = is_market_open(now)
    
    # Calculate next open time
    next_open = None
    next_close = None
    
    if market_open:
        # Market is open, next close is today at 4:00 PM
        next_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        next_open = next_close  # For consistency
    else:
        # Find next weekday
        days_ahead = 0
        current_day = now.weekday()
        
        # If it's Friday after 4 PM, next open is Monday
        if current_day == 4 and now.time() > datetime.time(16, 0):
            days_ahead = 3  # Friday to Monday
        else:
            # Find next weekday
            days_ahead = (7 - current_day) % 7 or 7
            if days_ahead > 0:
                days_ahead -= 1  # Skip current day
        
        next_open = now + datetime.timedelta(days=days_ahead)
        next_open = next_open.replace(hour=9, minute=30, second=0, microsecond=0)
        
        # Next close is same day at 4:00 PM
        next_close = next_open.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return {
        "timestamp": now.isoformat(),
        "market_open": market_open,
        "current_time": now.strftime("%I:%M %p"),
        "day_of_week": now.strftime("%A"),
        "next_open": next_open.isoformat() if next_open else None,
        "next_close": next_close.isoformat() if next_close else None
    }

if __name__ == "__main__":
    status = get_market_status()
    print(json.dumps(status, indent=2))
