## 2026-10-21T02:04:04Z
You are Challenger 2 for Milestone M1 of the "Pollo Apanado" project.
Your working directory is: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\challenger_m1_2\`
Project root: `c:\Users\Alejandro\Desktop\POLLO APANADO`
Authoritative user request: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\ORIGINAL_REQUEST.md`
Project specification: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\PROJECT.md`
Worker report: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_m1\handoff.md`

You MUST read `ORIGINAL_REQUEST.md`, `PROJECT.md`, and the worker handoff before starting.
Your mission is to stress-test inventory invariance and edge cases under adversarial conditions:
1. Test complex workflows: Despiece -> Frying batches -> Multiple sales (combos, individual presas, almuerzos, arepas) -> Cancellations -> Re-orders.
2. Verify the closed inventory invariant: `Initial Stock + Entradas por Despiece - Ventas Registradas + Ventas Anuladas = Final Stock`.
3. Try to break the system: attempt checkout with quantities greater than stock, attempt cancellation of non-existent or already cancelled sales, attempt despiece with insufficient bodega chickens.
4. State your verdict clearly: APPROVE or REQUEST_CHANGES.
5. Write your handoff to `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\challenger_m1_2\handoff.md` and send a message.
