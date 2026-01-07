import json
import os


def add_to_investment(amount: int) -> None:
    assert (amount > 0), f"amount must be positive! got {amount}"

    print(f"about to invest {amount}\n")

    with open("../currentInv.json", 'r') as f:
        inv_data = json.load(f)

        # Part 1 - input validation and stock aggregation

        stocks_to_purchase = {}

        percentage_sum = 0
        amounts_sum = 0
        for investment in inv_data["funds"]:
            name = investment['name']

            investment_amount = investment["amount"]
            assert (investment_amount >= 0), f"Illegal amount at investment {name}: {investment_amount}"
            amounts_sum += investment_amount

            assert 'targetPercentage' not in investment or 'countAs' not in investment, \
                f"Investment {name} has both a target percentage and counts as a different stock"

            if 'countAs' in investment:
                add_to_stock = investment['countAs']
                if add_to_stock in stocks_to_purchase:
                    stocks_to_purchase[add_to_stock]["funds"] += investment_amount
                else:
                    stocks_to_purchase[add_to_stock] = {"funds": investment_amount}
            else:
                target_percentage = investment["targetPercentage"]
                assert (target_percentage >= 0), f"Illegal target percentage at investment {name}: {target_percentage}"

                assert (target_percentage > 0 or investment_amount > 0), \
                       f"investment {name} has zero funds and zero amount so can it be removed from the json file"
                if name in stocks_to_purchase:
                    stocks_to_purchase[name]["funds"] += investment_amount
                else:
                    stocks_to_purchase[name] = {"funds": investment_amount}
                stocks_to_purchase[name]["targetPercentage"] = target_percentage
                percentage_sum += target_percentage

        assert (percentage_sum == 100), f"Sum of all percentages is not 100%! It is only {percentage_sum}%"

        for stock in stocks_to_purchase:
            assert "targetPercentage" in stocks_to_purchase[stock], \
                f"A stock was counted as a non-existent stock {stock}"

        # Part 2 - calculate purchases.

        tot_new_sum = amounts_sum + amount
        print(f"old total sum is {amounts_sum}")
        print(f"New total sum is {tot_new_sum}\n")

        # Remove stocks with negative purchases

        results = []  # list of strings to print
        sum_to_balance = tot_new_sum
        tot_percentage_to_balance = 100

        while True:
            results = []
            stocks_with_negative_purchases = set()
            print(f"DEBUG: sum to balance = {sum_to_balance}, "
                  f"total percentage to balance = {tot_percentage_to_balance}")

            for stock in stocks_to_purchase:
                investment = stocks_to_purchase[stock]
                wanted_amount = (sum_to_balance * investment["targetPercentage"]) / tot_percentage_to_balance
                delta = int(wanted_amount - investment["funds"])
                results.append(f"Need to invest {delta} in {stock}")
                if delta < 0:
                    stocks_with_negative_purchases.add(stock)

            print("DEBUG: " + '\n'.join(results))

            if stocks_with_negative_purchases:
                print("\nBy default, we do not allow negative purchases, "
                      "ignoring negative purchases stocks and dividing investment amongst the remaining stocks\n")

                for stock in stocks_with_negative_purchases:
                    sum_to_balance -= stocks_to_purchase[stock]["funds"]
                    tot_percentage_to_balance -= stocks_to_purchase[stock]["targetPercentage"]
                    stocks_to_purchase.pop(stock)

            else:
                break
        print(f"\nFinal results:\n", '\n'.join(results))


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    assert(len(os.sys.argv) > 1), "Must provide an amount to invest"
    assert(len(os.sys.argv) == 2), "too many program arguments were passed"
    amount_to_invest = os.sys.argv[1]
    try:
        amount_to_invest = int(amount_to_invest)
    except ValueError:
        raise ValueError(f"Expected int argument as value to invest, found {amount_to_invest}")

    add_to_investment(amount_to_invest)
