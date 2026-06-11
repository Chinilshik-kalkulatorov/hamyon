from .exceptions import InvalidTransition


class StateMachineMixin:
    """Explicit state transitions for models with a ``status`` field.

    Subclasses define ``ALLOWED = {current_status: {next_status, ...}}``.
    Invalid transitions raise — never silently ignored.
    """

    ALLOWED = {}

    def transition_to(self, new_status, extra_update_fields=()):
        allowed = self.ALLOWED.get(self.status, set())
        if new_status not in allowed:
            raise InvalidTransition(
                f"{type(self).__name__}: {self.status} -> {new_status} is not allowed"
            )
        self.status = new_status
        update_fields = ["status", *extra_update_fields]
        if any(f.name == "updated_at" for f in self._meta.fields):
            update_fields.append("updated_at")
        self.save(update_fields=update_fields)
