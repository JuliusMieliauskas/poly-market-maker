import logging
from math import sqrt

from poly_market_maker.token import Token, Collateral
from poly_market_maker.order import Order, Side
from poly_market_maker.utils import math_round_down


class AMMConfig:
    def __init__(
        self,
        p_min: float,
        p_max: float,
        spread: float,
        delta: float,
        depth: float,
        max_collateral: float,
        min_tick: float,
        min_size: float
    ):
        assert isinstance(p_min, float)
        assert isinstance(p_max, float)
        assert isinstance(delta, float)
        assert isinstance(depth, float)
        assert isinstance(spread, float)
        assert isinstance(max_collateral, float)

        self.p_min = p_min
        self.p_max = p_max
        self.delta = delta
        self.spread = spread
        self.depth = depth
        self.max_collateral = max_collateral
        self.min_tick = min_tick
        self.min_size = min_size


class AMM:
    def __init__(self, token: Token, config: AMMConfig):
        self.logger = logging.getLogger(self.__class__.__name__)

        assert isinstance(token, Token)

        if config.spread >= config.depth:
            raise Exception("Depth does not exceed spread.")

        self.token = token
        self.p_min = config.p_min
        self.p_max = config.p_max
        self.delta = config.delta
        self.spread = config.spread
        self.depth = config.depth
        self.max_collateral = config.max_collateral
        self.min_tick = config.min_tick
        self.min_size = config.min_size

    def count_decimal_places(self, number: float) -> int:
        # Counts number of decimal places in a float, e.g. 0.001 -> 3, 0.01 -> 2
        number_str = str(number)
        if '.' in number_str:
            decimal_part = number_str.split('.')[1]
            return len(decimal_part)
        else:
            return 0
        
    def update_spread(self, spread: float):
        self.spread = spread
        
    def set_price(self, p_i: float):
        self.p_i = p_i
        self.p_u = round(min(p_i + self.depth, self.p_max), self.count_decimal_places(self.min_tick))
        self.p_l = round(max(p_i - self.depth, self.p_min), self.count_decimal_places(self.min_tick))

        self.buy_prices = []
        price = round(self.p_i - self.spread, self.count_decimal_places(self.min_tick))
        while price >= self.p_l:
            self.buy_prices.append(price)
            price = round(price - self.delta, self.count_decimal_places(self.min_tick))

        self.sell_prices = []
        price = round(self.p_i + self.spread, self.count_decimal_places(self.min_tick))
        while price <= self.p_u:
            self.sell_prices.append(price)
            price = round(price + self.delta, self.count_decimal_places(self.min_tick))
        self.logger.debug(f"Token: {self.token}, Buy prices: {self.buy_prices}")
        self.logger.debug(f"Token: {self.token}, Sell prices: {self.sell_prices}")

    def get_sell_orders(self, x):
        sizes = [
            # round down to avoid too large orders
            math_round_down(size, 2)
            for size in self.diff([self.sell_size(x, p_t) for p_t in self.sell_prices])
        ]

        orders = [
            Order(
                price=price,
                side=Side.SELL,
                token=self.token,
                size=size,
            )
            for (price, size) in zip(self.sell_prices, sizes) if size >= self.min_size
        ]

        return orders

    def get_buy_orders(self, y):
        # y - total ammount of collateral allocated for token
        sizes_before_diff = [self.buy_size(y, p_t) for p_t in self.buy_prices]
        self.logger.debug(f"Sizes before diff: {sizes_before_diff}")

        sizes = [
            # round down to avoid too large orders
            math_round_down(size, 2)
            for size in self.diff(sizes_before_diff)
        ]
        self.logger.debug(f"Sizes after diff: {sizes}")

        orders = [
            Order(
                price=price,
                side=Side.BUY,
                token=self.token,
                size=size,
            )
            for (price, size) in zip(self.buy_prices, sizes) if size >= self.min_size
        ]

        return orders

    def phi(self):
        return (1 / (sqrt(self.p_i) - sqrt(self.p_l))) * (
            1 / sqrt(self.buy_prices[0]) - 1 / sqrt(self.p_i)
        )

    def sell_size(self, x, p_t):
        return self._sell_size(x, self.p_i, p_t, self.p_u)

    @staticmethod
    def _sell_size(x, p_i, p_t, p_u):
        L = x / (1 / sqrt(p_i) - 1 / sqrt(p_u))
        a = L / sqrt(p_u) - L / sqrt(p_t) + x
        return a

    def buy_size(self, y, p_t):
        self.logger.debug(f"Buy size: y={y}, p_t={p_t}")
        return self._buy_size(y, self.p_i, p_t, self.p_l)

    @staticmethod
    def _buy_size(y, p_i, p_t, p_l):
        L = y / (sqrt(p_i) - sqrt(p_l))
        a = L * (1 / sqrt(p_t) - 1 / sqrt(p_i))
        return a

    @staticmethod
    def diff(arr: list[float]) -> list[float]:
        return [arr[i] if i == 0 else arr[i] - arr[i - 1] for i in range(len(arr))]


class AMMManager:
    def __init__(self, config: AMMConfig):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.amm_a = AMM(token=Token.A, config=config)
        self.amm_b = AMM(token=Token.B, config=config)
        self.max_collateral = config.max_collateral

    def get_expected_orders(
        self,
        target_prices,
        balances,
        market_spread
    ):
        order_spread = market_spread
        if order_spread < 0.01:
            order_spread = 2 * market_spread # double the spread for the markets with low spread
            
        self.amm_a.update_spread(order_spread)
        self.amm_b.update_spread(order_spread)
        
        self.logger.debug(f"Setting prices for AMM")
        self.amm_a.set_price(target_prices[Token.A])
        self.amm_b.set_price(target_prices[Token.B])

        self.logger.debug(f"Getting orders for AMM")
        sell_orders_a = self.amm_a.get_sell_orders(balances[Token.A])
        sell_orders_b = self.amm_b.get_sell_orders(balances[Token.B])
        self.logger.debug(f"Sell orders A: {sell_orders_a}")
        self.logger.debug(f"Sell orders B: {sell_orders_b}")
        amount_of_sell_orders_in_dollars_A = sum(
            [order.size * order.price for order in sell_orders_a]
        )
        amount_of_sell_orders_in_dollars_B = sum(
            [order.size * order.price for order in sell_orders_b]
        )
        self.logger.debug(f"Amount of sell orders in dollars A: {amount_of_sell_orders_in_dollars_A}")
        self.logger.debug(f"Amount of sell orders in dollars B: {amount_of_sell_orders_in_dollars_B}")

        best_sell_order_size_a = sell_orders_a[0].size if len(sell_orders_a) > 0 else 0
        best_sell_order_size_b = sell_orders_b[0].size if len(sell_orders_b) > 0 else 0

        total_collateral_allocation = min(balances[Collateral], self.max_collateral)
        self.logger.debug(f"Total collateral allocation: {total_collateral_allocation}")

        self.logger.debug(f"Calculating collateral allocation")
        (collateral_allocation_a, collateral_allocation_b) = self.collateral_allocation(
            total_collateral_allocation,
            best_sell_order_size_a,
            best_sell_order_size_b,
        )
        self.logger.debug(f"Collateral allocation A: {collateral_allocation_a}")
        self.logger.debug(f"Collateral allocation B: {collateral_allocation_b}")

        self.logger.debug(f"Getting buy orders for AMM")
        buy_orders_a = self.amm_a.get_buy_orders(collateral_allocation_a)
        buy_orders_b = self.amm_b.get_buy_orders(collateral_allocation_b)
        self.logger.debug(f"Buy orders A: {buy_orders_a}")
        self.logger.debug(f"Buy orders B: {buy_orders_b}")

        orders = sell_orders_a + sell_orders_b + buy_orders_a + buy_orders_b

        return orders

    def collateral_allocation(
        self,
        collateral_balance: float,
        best_sell_order_size_a: float,
        best_sell_order_size_b: float,
    ):
        collateral_allocation_a = (
            best_sell_order_size_a
            - best_sell_order_size_b
            + collateral_balance * self.amm_b.phi()
        ) / (self.amm_a.phi() + self.amm_b.phi())

        if collateral_allocation_a < 0:
            collateral_allocation_a = 0
        elif collateral_allocation_a > collateral_balance:
            collateral_allocation_a = collateral_balance
        collateral_allocation_b = collateral_balance - collateral_allocation_a

        return (
            math_round_down(collateral_allocation_a, 2),
            math_round_down(collateral_allocation_b, 2),
        )
