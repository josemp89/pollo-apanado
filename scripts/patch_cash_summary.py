with open('app/routers/cash.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = """        # 4. Fórmula R1: Conciliación de Efectivo (descuenta solo egresos en efectivo)
        expected_cash = base_inicial + totals_dict["efectivo"] - total_expenses_cash
        actual_cash = shift_info["actual_cash"] if shift_info else None
        difference = (actual_cash - expected_cash) if actual_cash is not None else None

        cash_reconciliation = {
            "base_inicial": base_inicial,
            "cash_sales": totals_dict["efectivo"],
            "total_expenses": total_expenses,
            "expected_cash": expected_cash,
            "actual_cash": actual_cash,
            "difference": difference,
            "digital_transfers": totals_dict["nequi_daviplata"],
            "card_vouchers": totals_dict["datafono"],
            "gran_total_sales": totals_dict["gran_total"],
            "total_liquidity": expected_cash + totals_dict["nequi_daviplata"] + totals_dict["datafono"]
        }"""

replacement = """        # 4. Fórmula R1: Conciliación de Efectivo (descuenta solo egresos en efectivo)
        if shift_info and shift_info.get("status") == "cerrado":
            # Si el turno está formalmente cerrado, los valores oficiales son los consolidados en cash_shifts
            eff_cash_sales = shift_info.get("cash_sales") if shift_info.get("cash_sales") is not None else totals_dict["efectivo"]
            eff_digital_sales = shift_info.get("digital_sales") if shift_info.get("digital_sales") is not None else totals_dict["nequi_daviplata"]
            eff_datafono_sales = shift_info.get("datafono_sales") if shift_info.get("datafono_sales") is not None else totals_dict["datafono"]
            eff_total_sales = shift_info.get("total_sales") if shift_info.get("total_sales") is not None else (eff_cash_sales + eff_digital_sales + eff_datafono_sales)
            eff_total_expenses = shift_info.get("total_expenses") if shift_info.get("total_expenses") is not None else total_expenses
            expected_cash = shift_info.get("expected_cash") if shift_info.get("expected_cash") is not None else (base_inicial + eff_cash_sales - eff_total_expenses)
            actual_cash = shift_info.get("actual_cash") if shift_info.get("actual_cash") is not None else expected_cash
            difference = shift_info.get("difference", 0)

            totals_dict["efectivo"] = eff_cash_sales
            totals_dict["nequi_daviplata"] = eff_digital_sales
            totals_dict["datafono"] = eff_datafono_sales
            totals_dict["gran_total"] = eff_total_sales

            cash_reconciliation = {
                "base_inicial": base_inicial,
                "cash_sales": eff_cash_sales,
                "total_expenses": eff_total_expenses,
                "expected_cash": expected_cash,
                "actual_cash": actual_cash,
                "difference": difference,
                "digital_transfers": eff_digital_sales,
                "card_vouchers": eff_datafono_sales,
                "gran_total_sales": eff_total_sales,
                "total_liquidity": expected_cash + eff_digital_sales + eff_datafono_sales
            }
        else:
            expected_cash = base_inicial + totals_dict["efectivo"] - total_expenses_cash
            actual_cash = shift_info["actual_cash"] if shift_info else None
            difference = (actual_cash - expected_cash) if actual_cash is not None else None

            cash_reconciliation = {
                "base_inicial": base_inicial,
                "cash_sales": totals_dict["efectivo"],
                "total_expenses": total_expenses,
                "expected_cash": expected_cash,
                "actual_cash": actual_cash,
                "difference": difference,
                "digital_transfers": totals_dict["nequi_daviplata"],
                "card_vouchers": totals_dict["datafono"],
                "gran_total_sales": totals_dict["gran_total"],
                "total_liquidity": expected_cash + totals_dict["nequi_daviplata"] + totals_dict["datafono"]
            }"""

# Normalize CRLF
if target.replace('\r\n', '\n') in text.replace('\r\n', '\n'):
    text = text.replace('\r\n', '\n')
    text = text.replace(target.replace('\r\n', '\n'), replacement.replace('\r\n', '\n'))
    with open('app/routers/cash.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched app/routers/cash.py successfully")
else:
    print("Target not found in app/routers/cash.py")
