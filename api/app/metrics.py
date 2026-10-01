from prometheus_client import Counter, Histogram

REQUESTS = Histogram(
    "tixlab_http_request_duration_seconds", "HTTP request latency", ["method", "route", "status"]
)
HOLDS = Counter("tixlab_holds_total", "Seat hold attempts", ["result"])
BOOKINGS = Counter("tixlab_bookings_total", "Confirmed bookings")
QUEUE_JOINS = Counter("tixlab_queue_joins_total", "Fans who joined a waiting room")
CHECKINS = Counter("tixlab_checkins_total", "Door scans", ["result"])
