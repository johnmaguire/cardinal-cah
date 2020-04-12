import os
import logging
from random import shuffle
from threading import Lock
from collections import deque

DEFAULT_HAND_SIZE = 10


class InvalidMoveError(Exception):
    pass


class InvalidPickError(InvalidMoveError):
    pass


class InvalidChoiceError(InvalidMoveError):
    pass


class PlayerExistsError(Exception):
    pass


class NotEnoughPlayersError(Exception):
    pass


class Player(object):
    WAITING = 1
    CHOOSING = 2
    PICKING = 3

    def __init__(self, name, game):
        self.state = self.WAITING
        self.points = 0
        self.hand = []

        self.name = name
        self.game = game

    def draw(self, hand_size=DEFAULT_HAND_SIZE):
        """Draws cards from the white deck until hand is full.

        Keyword arguments:
          hand_size -- Defaults to 10. Useful for draw 2, pick 3.
        """
        while len(self.hand) < hand_size and len(self.game.deck['white']):
            self.hand.append(self.game.deck['white'].pop())

    def choose(self, cards):
        """Choose cards to play.

        Raises:
          InvalidMoveError -- If it's not the player's turn.
          InvalidChoiceError -- An invalid card was chosen.
        """
        # Wrong time for player to choose
        if self.state != Player.CHOOSING:
            raise InvalidMoveError("Player isn't choosing cards now")

        # Stage the players choices
        choices = []

        try:
            for idx in cards:
                choices.append(self.hand[int(idx)])
        except Exception:
            raise InvalidChoiceError("[{}] isn't a valid choice".format(idx))

        choices = tuple(choices)

        # Let exceptions escape. This is why we staged our choices
        self.game.choose(self, choices)

        # Remove the cards from the player's hand
        for choice in choices:
            self.hand.remove(choice)

        # Draw cards for the player
        self.draw()

        self.state = Player.WAITING


class Game(object):
    STARTING = 1
    WAITING_CHOICES = 2
    WAITING_PICK = 3
    OVER = 4

    def __init__(self, max_points=5):
        self.logger = logging.getLogger(__name__)

        # Set max points to win
        self.max_points = max_points

        # Game storage
        self.players = {}
        self.choices = []
        self.scores = []
        self.lock = Lock()

        # Reset game state
        self.state = self.STARTING
        self.picker = None
        self.black_card = None
        self.required_cards = 0
        self.play_deque = deque()
        self.deck = {
            'white': self._load_deck('white'),
            'black': self._load_deck('black'),
        }

    def _load_deck(self, name):
        """Loads a deck by name (color)."""
        filename = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "{}.txt".format(name)
        )

        with open(filename, 'r') as deck:
            cards = deck.read().strip().split("\n")

        # remove commented out cards
        for card in cards:
            if card[:1] == '#':
                cards.remove(card)

        shuffle(cards)

        return cards

    def ready(self):
        """Starts the game and returns the picker and black card.

        Raises:
          InvalidMoveError -- If a game is already in progress.
          NotEnoughPlayersError -- If there aren't at least 3 players.
        """
        if self.state != self.STARTING:
            raise InvalidMoveError

        if len(self.players) < 3:
            raise NotEnoughPlayersError

        self._prepare_round()

        return

    def _prepare_round(self):
        """Starts a new round or ends the game if a win condition is hit.

        Game ends if either deck is depleted, or someone has max points.

        Sets the next picker, resets the choice list, sets player states,
        draws a new black card, and sets the required number of chosen cards,
        and sets the game state.
        """
        # if the game is starting, shuffle the decks
        if self.state == self.STARTING:
            for _, deck in self.deck.items():
                shuffle(deck)

        for _, player in self.players.items():
            # Check if a player won
            if player.points == self.max_points:
                self._end_game()
                return

            # Draw cards
            player.draw()

        # Game ends if we are out of cards
        if len(self.deck['white']) == 0 or len(self.deck['black']) == 0:
            self._end_game()
            return

        # Set the picker and move them to the end of the queue
        self.picker = self.play_deque.pop()
        self.play_deque.appendleft(self.picker)

        # Reset choices
        self.choices = []

        # Update player states
        for player in self.players:
            self.players[player].state = Player.CHOOSING
        self.picker.state = Player.WAITING

        # Choose a black card and determine the number of blanks
        self.black_card = self.deck['black'].pop()

        self.required_cards = self.black_card.count('%s')

        # Some cards have no blanks. They require 1 white card
        if self.required_cards == 0:
            self.required_cards = 1

        self.state = self.WAITING_CHOICES

    def _end_game(self):
        """Tallies results and ends the game."""
        self._tally_scores()
        self.state = self.OVER

    def add_player(self, name):
        """Adds a player to the game.

        Raises:
          InvalidMoveError -- If the game isn't starting.
          PlayerExistsError -- If the player already exists.
        """
        name = str(name)

        if self.state != self.STARTING:
            raise InvalidMoveError

        if name in self.players:
            raise PlayerExistsError("{} is already playing".format(name))

        player = Player(name, self)
        self.players[name] = player

        # Add player to the play queue and re-shuffle it
        self.play_deque.append(player)
        shuffle(self.play_deque)

    def remove_player(self, name):
        """Removes a player from the game.

        Raises:
          KeyError -- If the player doesn't exist.
        """
        name = str(name)
        player = self.players[name]

        # remove the player from the list of players and play order
        del self.players[name]
        self.play_deque.remove(self.players[name])

        # put their cards back into the deck
        while player.hand:
            card = player.hand.pop()
            self.deck['white'].append(card)

        # and remove their chosen card if they have one
        for idx, choice in enumerate(self.choices):
            if choice[0] == player:
                del self.choices[idx]
                self.deck['white'].append(choice)

        # shuffle the deck in case they put cards back
        shuffle(self.deck['white'])

        # Check if we don't have enough players now
        if self.state != self.STARTING and len(self.players) < 3:
            self._end_game()
            return

        # If we were waiting for this player to play, move on with the game
        if (self.state == self.WAITING_CHOICES and
                len(self.players) - 1 == len(self.choices)):
            self._prepare_picks()

        # If this player was supposed to pick, skip the round
        elif self.state != self.STARTING and self.picker.name == name:
            # give players their choices back
            for choice in self.choices:
                player, card = choice
                player.hand.append(card)

            self._prepare_round()

    def _prepare_picks(self):
        """Prepares picks.

        Shuffles the player choices and sets game state.
        """
        # Create an shuffled list of player, choice tuples
        shuffle(self.choices)

        self.picker.state = Player.PICKING
        self.state = self.WAITING_PICK

    def _tally_scores(self):
        # Tally up new scores
        players = sorted(self.players.items(), key=lambda p: p[1].points)
        players.reverse()

        self.scores = players

    def pick(self, choice):
        """Pick a round winner.

        Raises:
          InvalidMoveError -- If the game isn't waiting for a pick.
          IndexError -- If the choice is invalid.
        """
        if self.state != self.WAITING_PICK:
            raise InvalidMoveError("Wrong time to pick a winner")

        try:
            pick = self.choices[int(choice)]
        except IndexError:
            raise InvalidPickError("{} wasn't an option".format(choice))

        # Give the winner points
        pick[0].points += 1

        # Update scores
        self._tally_scores()

        # Start the next round
        self._prepare_round()

        return pick

    def choose(self, player, cards):
        """Chooses cards from a player's hand to play.

        Raises:
          InvalidMoveError -- If this is the wrong time to play.
          InvalidChoiceError -- If the choice of cards isn't valid.
          ValueError -- If the wrong number of cards are played.
        """
        # Wrong time to play a card
        if self.state != self.WAITING_CHOICES:
            raise InvalidMoveError("Wrong time to play cards")

        # Not the right amount of cards
        if len(cards) != self.required_cards:
            raise InvalidChoiceError("You must choose {} cards"
                                     .format(self.required_cards))

        # Fill in blanks if there are any
        choice = ''
        if '%s' not in self.black_card:
            choice = cards[0]
        elif self.black_card.count('%s') == 1:
            choice = self.black_card % cards[0]
        elif self.black_card.count('%s') >= 2:
            choice = self.black_card % cards

        # Save player choices
        self.choices.append((player, choice))

        # If all players have made their choices, change the game state
        if len(self.players) - 1 == len(self.choices):
            self._prepare_picks()

    def close(self):
        # Prevent cyclic references during GC
        del self.picker
        self.deck.clear()
        self.players.clear()
        self.play_deque.clear()
