import unittest

from focus import Session


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.session = Session("Solve two capacitor exercises", "Draw the circuit", 5,
                               clock=lambda: self.now)

    def test_objective_first_step_and_duration(self):
        self.assertEqual(self.session.objective, "Solve two capacitor exercises")
        self.assertEqual(self.session.first_step, "Draw the circuit")
        self.assertEqual(self.session.remaining(), 300)
        self.now += 60
        self.assertEqual(self.session.remaining(), 240)

    def test_pause_and_resume_preserve_remaining_time(self):
        self.now += 20
        self.session.toggle_pause()
        self.now += 100
        self.assertEqual(self.session.remaining(), 280)
        self.session.toggle_pause()
        self.now += 10
        self.assertEqual(self.session.remaining(), 270)

    def test_distraction_does_not_reset_timer(self):
        self.now += 30
        self.session.add_distraction("Reply to a message")
        self.assertEqual(self.session.distractions, ["Reply to a message"])
        self.assertEqual(self.session.remaining(), 270)
        self.session.add_distraction("   ")
        self.assertEqual(self.session.distractions, ["Reply to a message"])

    def test_expiry_is_clamped_and_closes_focus(self):
        self.now += 301
        self.assertEqual(self.session.remaining(), 0)
        self.assertEqual(self.session.phase, "reflection")
        self.assertEqual(self.session.focus_seconds, 300)

    def test_finish_records_progress_and_next_step_then_optional_rest(self):
        self.now += 40
        self.session.finish()
        self.assertEqual(self.session.phase, "reflection")
        self.assertEqual(self.session.focus_seconds, 40)
        self.session.reflect("Solved exercise one", "Start exercise two")
        self.assertEqual(self.session.progress, "Solved exercise one")
        self.assertEqual(self.session.next_step, "Start exercise two")
        self.session.start_break()
        self.assertEqual(self.session.phase, "break")
        self.assertEqual(self.session.remaining(), 300)
        self.now += 300
        self.assertEqual(self.session.remaining(), 0)
        self.assertEqual(self.session.phase, "done")
        self.assertEqual(self.session.focus_seconds, 40)

    def test_empty_objective_or_step_and_invalid_duration_are_rejected(self):
        for objective, step, minutes in [(" ", "Read", 5), ("Study", "", 5),
                                          ("Study", "Read", 0), ("Study", "Read", -1)]:
            with self.subTest(objective=objective, step=step, minutes=minutes):
                with self.assertRaises(ValueError):
                    Session(objective, step, minutes)


if __name__ == "__main__":
    unittest.main()
