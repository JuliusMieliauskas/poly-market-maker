import logging

from poly_market_maker.token import Token


class Market:
    def __init__(self, condition_id: str, tokenA: object, tokenB: object):
        self.logger = logging.getLogger(self.__class__.__name__)

        assert isinstance(condition_id, str)
        assert isinstance(tokenA, object)
        assert isinstance(tokenB, object)

        self.condition_id = condition_id
        self.tokenA = tokenA
        self.tokenB = tokenB

        self.logger.info(f"Initialized Market: {self}")

    def __repr__(self):
        return f"Market[condition_id={self.condition_id}, token_id_a={self.get_token_id(Token.A)}, token_id_b={self.get_token_id(Token.B)}]"

    def get_token_id(self, token: Token):
        return self.tokenA["token_id"] if token == Token.A else self.tokenB["token_id"]
    
    def get_token(self, token: Token):
        return self.tokenA if token == Token.A else self.tokenB
    
    def get_token_side_by_id(self, token_id: str) -> Token:
        return Token.A if self.tokenA["token_id"] == token_id else Token.B
