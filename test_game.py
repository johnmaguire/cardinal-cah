from game import (
    DEFAULT_HAND_SIZE,
    Game,
    Player,
)


class TestPlayer(object):
    def setup_method(self):
        self.game = Game()
        self.player = Player('player1', self.game)

    def test_pick_2(self):
        self.player.draw()
        assert len(self.player.hand) == DEFAULT_HAND_SIZE

        # put the player in choosing state
        self.player.state = Player.CHOOSING
        self.game.state = Game.WAITING_CHOICES
        self.game.required_cards = 2
        self.game.black_card = '%s %s'

        # reveal cards at indexes 0 and 5
        choices = (self.player.hand[0], self.player.hand[5])

        # choose those indexes
        self.player.choose((0, 5))

        # make sure the two cards are gone
        for choice in choices:
            assert choice not in self.player.hand
