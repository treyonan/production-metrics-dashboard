# Problems Identified
Although it was a robust start, and the AI helped us create a lot of code to get this REST API started, the initial iteration of this application had some drawbacks:

## Data Integrity Problems
- iteration 0 of this REST API allows for the following referential integrity problems
  - foreign keys, `FK`, are not enforced
  - examples:
    - instances of `Branch` can be added without having a reference to which `library_system` the branch belongs
    - a `Loan` can be created for bogous `FK` ids for `Branch`, `Patron`, or `Book`
- there are similar problems with many of the other `entities`

## Structural Data Problems
- there is a limitation between the `Authors` and `Books` entities. A book can only have a single author. Books with multiple authors cannot be added to the collection of books.
- there is a limitation on tracking copies of a book. The current model has a few limitations
  - only a single copy of a book can be stored in the entire library system
  - it is not clear at which branch is a copy of the book on-hand
  - scaling up to dozens of 1000s of books is not going to be feasible

# Software Quality Attributes (a.k.a. NFRs)
This section contains high-level information about cross-cutting quality attributes that should be considered when creating REST APIs for any domain.  The intent here is to make you aware of these quality attirbutes as you consider the scope, feature-set and investment you would like to make to strengthenten your REST API.  In traditional softwre engineering, these are also know as `Non-Functional Requirements`. Follow [this link](https://www.sei.cmu.edu/library/quality-attributes/) for more information about Software Quality Attributes.

### Performance
- Response Time: API endpoints (e.g., GET /api/books, POST /api/loans) must respond within 200ms under normal load (95th percentile) for queries returning <100 records.
- Throughput: Support at least 100 requests per second for read operations (e.g., GET /api/authors) and 20 requests per second for write operations (e.g., POST /api/books).
- Latency Under Load: Maintain <500ms latency for all endpoints under peak load (e.g., 500 concurrent users during library events).
- Database Query Efficiency: Optimize SQLAlchemy queries (e.g., for books.author_id joins) to execute in <50ms with appropriate indexing.

### Scalability
- Horizontal Scaling: API must support deployment across multiple nodes (e.g., via Kubernetes) to handle increased traffic (e.g., 10,000 daily active users).
- Database Scalability: Support sharding or read replicas for the database (e.g., PostgreSQL) to handle growth in book and loan records (target: 1M+ books).
- Load Balancing: Integrate with a load balancer (e.g., Nginx) to distribute requests evenly across Uvicorn workers.

### Availability and Reliability
- Uptime: Achieve 99.9% uptime (less than 8.76 hours of downtime per year), excluding scheduled maintenance.
- Fault Tolerance: Handle database connection failures gracefully (e.g., retry logic for SQLAlchemy sessions) with <1% request failure rate.
- Redundancy: Deploy in at least two availability zones (e.g., AWS regions) to ensure continuity during server outages.
- Error Handling: Return meaningful HTTP status codes (e.g., 404 for non-existent /api/books/999, 422 for invalid author_id) with JSON error messages.

### Security
- Authentication: Require JWT-based authentication for write endpoints (e.g., POST /api/loans) to restrict access to authorized librarians/patrons.
- Authorization: Implement role-based access control (e.g., admin vs. patron roles) to limit endpoint access (e.g., only admins can DELETE /api/branches).
- Data Encryption: Use HTTPS (TLS 1.3) for all API traffic; encrypt sensitive fields (e.g., patron PII) in transit and at rest (e.g., AES-256 in database).
- Input Validation: Use Pydantic to validate all inputs (e.g., ISBN format for /api/books) to prevent injection attacks (SQL, XSS).
- Rate Limiting: Enforce 100 requests per minute per user/IP to mitigate abuse (e.g., DDoS attacks on /api/patrons).

### Maintainability
- Code Modularity: Structure code (e.g., FastAPI routers, SQLAlchemy models) to allow adding new resources (e.g., /api/publishers) with <1 day of effort.
- Documentation: Provide OpenAPI (Swagger) docs at /docs with examples for all endpoints (e.g., POST /api/books sample payload).
- Versioning: Support API versioning (e.g., /api/v1/books) to allow backward-compatible updates without breaking clients.
- Logging: Log all requests and errors (e.g., via Python’s logging or FastAPI middleware) with timestamps and correlation IDs for debugging.

### Usability
- API Discoverability: Auto-generate clear, interactive Swagger UI (/docs) with endpoint descriptions, parameter constraints, and response schemas.
- Error Messages: Provide human-readable error details (e.g., {"detail": "Author with ID 999 not found"} for invalid author_id).
- Client Compatibility: Support JSON payloads and standard HTTP methods (GET, POST, PUT, DELETE) for easy integration with web/mobile clients.

### Interoperability
- Data Format: Use JSON for all request/response bodies, adhering to REST standards (e.g., HAL or JSON:API for relationships like book.author).
- Compatibility: Support integration with external systems (e.g., library catalog standards like MARC) via standardized endpoints or data exports.
- Cross-Origin Support: Enable CORS for specific domains (e.g., library’s web app) to allow browser-based clients to access /api routes.

### Portability
- Environment Agnostic: Run consistently in development (Windows, with Uvicorn --reload), staging, and production (Linux, Gunicorn + Uvicorn) environments.
- Containerization: Package API in Docker containers with a base image (e.g., python:3.13-slim) to ensure consistent deployment across clouds (AWS, Azure).
- Database Flexibility: Support multiple SQL databases (e.g., PostgreSQL, MySQL) via SQLAlchemy’s dialect system with minimal configuration changes.

### Compliance
- Data Privacy: Comply with GDPR/CCPA for patron data (e.g., right to delete /api/patrons/{id} data, consent for storing PII like emails).
- Accessibility: Ensure Swagger UI meets WCAG 2.1 AA for admin users with disabilities (e.g., screen reader support).
- Auditability: Log all write operations (e.g., POST /api/loans) with user IDs and timestamps for regulatory audits.

### Monitoring and Observability
- Metrics: Expose endpoint metrics (e.g., request latency, error rates) via Prometheus or similar for endpoints like /api/books.
- Health Checks: Provide a /api/health endpoint returning 200 OK with DB connection status and uptime.
- Alerting: Configure alerts for >5% error rates or latency spikes (>1s) on critical endpoints (e.g., POST /api/loans).

### Capacity
- Storage: Support at least 10GB of book/loan data (e.g., 1M books, 10M loans) without performance degradation.
- Concurrent Users: Handle 500 concurrent users during peak hours (e.g., library opening hours) with <1% request failures.
- Caching: Implement Redis or in-memory caching for frequent reads (e.g., GET /api/books?author_id=123) to reduce DB load.

### Recovery and Backup
- Backup Frequency: Perform daily database backups with 7-day retention for tables like books, authors, and loans.
- Disaster Recovery: Restore API and database to full operation within 4 hours after a critical failure (e.g., DB crash).
- Data Integrity: Ensure no data loss for committed transactions (e.g., POST /api/loans) using ACID-compliant databases.
