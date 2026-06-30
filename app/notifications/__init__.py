"""Outbound operational notifications (team alerts).

Pure rendering of internal notifications from durable domain entities. The
modules here never touch the database, secrets, or external transports; the
write path enqueues the rendered events and the dispatcher delivers them.
"""
