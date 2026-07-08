import time
import uuid
from collections import deque
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import structlog
from fastapi.responses import PlainTextResponse

# 1. Initialize FastAPI app
app = FastAPI()

# 2. Track Startup Time for /healthz
START_TIME = time.time()

# 3. Configure Prometheus Counter
# This automatically creates a counter called 'http_requests_total'
REQUEST_COUNTER = Counter("http_requests_total", "Total count of HTTP requests")

# 4. Configure Structured JSON Logging
# We use an in-memory deque to store the last 100 log entries so we can tail them
LOG_HISTORY = deque(maxlen=100)

def memory_logger_processor(logger, method_name, event_dict):
    """Custom processor to capture logs in memory for the /logs/tail endpoint."""
    # We make a copy to avoid mutating the log dictionary used by the console printer
    LOG_HISTORY.append(event_dict.copy())
    return event_dict

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso", key="ts"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
    wrapper_class=structlog.make_filtering_bound_logger(10), # DEBUG level
)

# Create a separate, internal structlog instance dedicated to capturing logs in memory
memory_logger = structlog.get_logger()
memory_logger = memory_logger.bind()
# Inject our custom memory buffer processor manually
memory_logger._processors.append(memory_logger_processor)


# 5. Middleware to intercept all incoming requests
# This automatically increments our counter and assigns a unique Request ID
@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    # Increment Prometheus counter for every single incoming request
    REQUEST_COUNTER.inc()
    
    # Generate a unique ID for this request
    request_id = str(uuid.uuid4())
    
    # Process the request and get the response
    response = await call_next(request)
    
    # Skip logging the log-tailing endpoint itself to avoid infinite feedback loops
    if "/logs/tail" not in request.url.path:
        memory_logger.info(
            event="request_processed",
            level="info",
            path=request.url.path,
            request_id=request_id
        )
        
    return response


# 6. Endpoints Implementation

@app.get("/work")
def do_work(n: int, email: str = "your_email@example.com"):
    """Simulates K units of work and returns confirmation."""
    # Perform 'n' units of work (e.g., a simple loop)
    for _ in range(n):
        pass
    return {"email": email, "done": n}


@app.get("/metrics", response_class=PlainTextResponse)
def get_metrics():
    """Exposes live Prometheus metrics cleanly as plain text."""
    # Decode the bytes from generate_latest() into a UTF-8 string
    metrics_data = generate_latest().decode("utf-8")
    return PlainTextResponse(content=metrics_data, media_type=CONTENT_TYPE_LATEST)



@app.get("/healthz")
def get_health():
    """Returns application status and precise uptime in seconds."""
    uptime = time.time() - START_TIME
    return {
        "status": "ok",
        "uptime_s": float(uptime)
    }


@app.get("/logs/tail")
def tail_logs(limit: int = 10):
    """Returns a JSON array of the last N log entries."""
    # Convert our deque history into a standard list
    all_logs = list(LOG_HISTORY)
    # Return only the requested number of recent logs
    return all_logs[-limit:]
