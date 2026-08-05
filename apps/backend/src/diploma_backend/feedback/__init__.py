"""Feedback signal capture (TASK-E09-1): approve/reject/edit signals on a chapter draft, tagged
with the institution template in play.

This package only records raw signals as an auditable log (E09's non-functional note: "which
user correction changed which weight" must stay traceable). It does not compute or apply any
`accuracy_weight` adjustment — that is TASK-E09-2, a separate, still-blocked task.
"""
