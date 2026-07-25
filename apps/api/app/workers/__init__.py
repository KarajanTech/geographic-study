"""Background workers.

Heavy geospatial work (viewsheds today; optimization solves later) runs here,
never inside an HTTP request. PostgreSQL doubles as the job queue: workers
poll for rows at ``pending`` rather than depending on a separate broker.
"""
