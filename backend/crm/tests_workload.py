"""Phase C: workload-aware assigning — the /api/tasks/workload/ panel data.
Informs the assigner, never blocks."""
from datetime import timedelta

from django.utils import timezone

from .models import Task, TaskStatus
from .tests_task_engine import Base


class WorkloadTests(Base):
    def _get(self, as_user, target):
        self.as_(as_user)
        return self.client.get(f"/api/tasks/workload/?user={target.id}")

    def test_numbers_exclude_done_and_deleted(self):
        mk = lambda **kw: Task.objects.create(assigned_to=self.rahul,
                                              created_by=self.manager, **kw)
        mk(title="A", priority="high", effort_minutes=60,
           due_at=timezone.now() - timedelta(hours=2))       # open + overdue
        mk(title="B", priority="urgent", effort_minutes=90)  # open
        mk(title="C")                                        # open, no effort
        mk(title="D", status=TaskStatus.DONE, effort_minutes=999,
           completed_at=timezone.now())                      # done — excluded
        mk(title="E", effort_minutes=500,
           deleted_at=timezone.now())                        # deleted — excluded

        res = self._get(self.manager, self.rahul)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["open_tasks"], 3)
        self.assertEqual(res.data["overdue"], 1)
        self.assertEqual(res.data["pending_effort_minutes"], 150)
        self.assertEqual(res.data["tasks_without_effort"], 1)
        self.assertEqual(res.data["priority_breakdown"]["high"], 1)
        self.assertEqual(res.data["priority_breakdown"]["urgent"], 1)
        self.assertEqual(res.data["priority_breakdown"]["normal"], 1)
        self.assertFalse(res.data["overloaded"])

    def test_overloaded_flag_on_full_day_of_effort(self):
        Task.objects.create(title="Big", assigned_to=self.amit,
                            created_by=self.manager, effort_minutes=8 * 60)
        res = self._get(self.manager, self.amit)
        self.assertTrue(res.data["overloaded"])

    def test_employee_sees_peer_but_not_upward(self):
        # rahul may assign to fellow employee amit -> workload visible
        self.assertEqual(self._get(self.rahul, self.amit).status_code, 200)
        # ...but not to his manager (can't assign upward, no dept capability)
        self.assertEqual(self._get(self.rahul, self.manager).status_code, 403)

    def test_unknown_user_rejected(self):
        self.as_(self.manager)
        self.assertEqual(self.client.get("/api/tasks/workload/?user=99999").status_code, 400)
        self.assertEqual(self.client.get("/api/tasks/workload/").status_code, 400)
