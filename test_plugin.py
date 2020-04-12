import copy

import pytest
from mock import Mock

from cardinal.bot import (
    CardinalBot,
    user_info,
)

from plugin import (
    DEFAULT_HAND_SIZE,
    CAHPlugin,
    Game,
    InvalidMoveError,
    Player,
    PlayerExistsError,
)


class TestPlugin(object):
    def setup_method(self):
        self.channel = '#channel'
        self.player = 'player1'
        self.user = user_info(self.player, 'user', 'vhost')

        self.mock_cardinal = Mock(spec=CardinalBot)
        self.mock_cardinal.nickname = 'Cardinal'

        self.plugin = CAHPlugin(self.mock_cardinal,
                                {'channel': '#cah'})

        self.plugin.game = Game()
        self.plugin.game.add_player(self.player)

    def test_choose_waiting_in_pm(self):
        # when command sent in pm, respond in pm
        self.plugin.choose(self.mock_cardinal,
                           self.user,
                           self.player,
                           ".choose 1")

        self.mock_cardinal.sendMsg.assert_called_once_with(
            self.player,
            "Please wait for your turn.",
        )

    def test_choose_waiting_in_channel(self):
        # went command sent in channel, respond in channel
        self.plugin.choose(self.mock_cardinal,
                           self.user,
                           self.channel,
                           ".choose 1")

        self.mock_cardinal.sendMsg.assert_called_once_with(
            self.channel,
            "Please wait for your turn.",
        )


class TestPlayer(object):
    def setup_method(self):
        self.game = Game()

        self.nick = 'player1'
        self.game.add_player(self.nick)
        self.player = self.game.players[self.nick]

    def test_draw(self):
        deck_length = len(self.game.deck['white'])

        self.player.draw()

        assert len(self.player.hand) == DEFAULT_HAND_SIZE
        assert len(self.game.deck['white']) == deck_length - DEFAULT_HAND_SIZE

    def test_draw_override_hand_size(self):
        hand_size = DEFAULT_HAND_SIZE + 2

        deck_length = len(self.game.deck['white'])

        self.player.draw(hand_size)

        assert len(self.player.hand) == hand_size
        assert len(self.game.deck['white']) == deck_length - hand_size

    def test_choose_2(self):
        self.player.draw()

        # put the player in choosing state
        self.player.state = Player.CHOOSING
        self.game.state = Game.WAITING_CHOICES
        self.game.required_cards = 2
        self.game.black_card = '%s %s'

        # reveal cards at indexes 0 and 5
        choices = (self.player.hand[0], self.player.hand[5])

        # choose those indexes
        self.player.choose((0, 5))

        # make sure the two correct cards are gone
        for choice in choices:
            assert choice not in self.player.hand

    def test_add_player(self):
        nick = 'player2'

        # this test relies on us being in the game starting state
        assert self.game.state == Game.STARTING

        count_players = len(self.game.players)
        self.game.add_player(nick)

        # make sure the player is added
        assert len(self.game.players) == count_players + 1
        assert nick in self.game.players.keys()
        player = self.game.players[nick]

        assert player in self.game.play_deque

    def test_add_player_twice_fails(self):
        self.game.add_player('player2')
        with pytest.raises(PlayerExistsError):
            self.game.add_player('player2')

    def test_remove_player(self):
        assert len(self.game.players) == 1
        assert len(self.game.play_deque) == 1

        self.player.draw()

        hand = copy.copy(self.player.hand)
        assert len(hand) > 0

        for card in hand:
            assert card not in self.game.deck['white']

        self.game.remove_player(self.nick)

        # make sure hand was put back into deck
        for card in hand:
            assert card in self.game.deck['white']

        # @TODO check that choice was put back also

        assert len(self.game.players) == 0
        assert len(self.game.play_deque) == 0

    @pytest.mark.parametrize('state', (
        (Game.WAITING_CHOICES,),
        (Game.WAITING_PICK,),
        (Game.OVER,),
    ))
    def test_add_player_invalid_state(self, state):
        self.game.state = state
        with pytest.raises(InvalidMoveError):
            self.game.add_player('player2')
