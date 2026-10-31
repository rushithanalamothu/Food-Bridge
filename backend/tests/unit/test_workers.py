from foodbridge.agents.celery_app import celery_app


def test_sender_uses_a_declared_default_queue():
    # Sender setup also resolves the default queue even for explicitly routed tasks.
    # With implicit queue creation disabled, leaving Celery's default breaks publish.
    assert celery_app.amqp.default_queue.name == "orchestrator"
    assert callable(celery_app.amqp.send_task_message)


def test_every_worker_module_is_registered_and_routed():
    celery_app.loader.import_default_modules()
    for name in ("orchestrator", "intake", "matching", "reservation"):
        task_name = f"foodbridge.{name}.probe"
        assert task_name in celery_app.tasks
        route = celery_app.amqp.router.route({}, task_name)
        assert route["queue"].name == name
