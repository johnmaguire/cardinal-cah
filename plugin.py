import os
import logging
from glob import glob
from random import shuffle
from collections import deque


from cardinal.decorators import command, event, help


class CAHPlugin(object):
    def __init__(self, cardinal, config):
        self.logger = logging.getLogger(__name__)
        self.cardinal = cardinal

        self.channel = config['channel']

        self.game = None

    @command('play')
    @help("Joins or starts a new Cardinals Against Humanity game")
    @help("Syntax: .play")
    def play(self, cardinal, user, channel, msg):
        nick = user.nick

        # Check if CAH is allowed here
        if channel != self.channel:
            return cardinal.sendMsg(nick,
                                    "Sorry, CAH isn't allowed here. Please "
                                    "join {} to start a game."
                                    .format(self.channel))

        # Attempt to get the game
        if not self.game:
            self.game = Game()
            self.game.add_player(nick)

            cardinal.sendMsg(
                channel, "A new game of Cardinal Against Humanity has been "
                         "created. You've been joined automatically. Other "
                         "players can use .play to join.")
            cardinal.sendMsg(
                channel, "When you're ready to start the game, just say "
                         ".ready and we'll begin. Have fun!")
            return

        try:
            self.game.add_player(nick)
        except InvalidMoveError:
            cardinal.sendMsg(channel, "The game is already in progress.")
            return
        except PlayerExistsError:
            cardinal.sendMsg(channel, "You're already playing :)")
            return

        cardinal.sendMsg(channel, "{} has joined the game.".format(nick))
        cardinal.sendMsg(channel, "Players: {}".format(', '.join([
            player for player in self.game.players
        ])))

    @command(['ready', 'start'])
    @help("Begin the CAH game!")
    @help('Syntax: .ready/.start')
    def ready(self, cardinal, user, channel, msg):
        if channel != self.channel:
            cardinal.sendMsg(channel, "Please start the game in {}."
                                      .format(self.channel))
            return

        if not self.game:
            cardinal.sendMsg(channel, "No game in progress. Say .play to "
                                      "start one!")
            return

        try:
            self.game.ready()
        except InvalidMoveError:
            cardinal.sendMsg(channel, "The game has already begun.")
            return
        except NotEnoughPlayersError:
            cardinal.sendMsg(channel, "Not enough players to begin the game!")
            return

        cardinal.sendMsg(channel, "The game has begun! We will be playing "
                                  "until someone earns {} points."
                                  .format(self.game.max_points))

        self.show_black_card()
        self.show_hands()

    @command(['choose', 'c'])
    @help("Choose cards to play")
    @help("Syntax: .choose <choice [choice, [..]]>")
    def choose(self, cardinal, user, channel, msg):
        """Play a card or card combination"""
        nick = user.nick

        # Get the choices
        choices = msg.strip().split(' ')[1:]

        if not self.game:
            if channel == self.channel:
                message = "No game in progress. Start one with .play!"
            else:
                message = "No game in progress. Start one in {}.".format(
                    self.channel)

            cardinal.sendMsg(channel, message)
            return

        try:
            player = self.game.players[nick]
        # Ignore invalid player
        except KeyError:
            cardinal.sendMsg(channel, "It doesn't look like you're playing. "
                                      "Join in next time!")

        if (self.game.state == Game.STARTING or
                player.state == Player.WAITING):
            cardinal.sendMsg(channel, "Please wait for your turn.")
            return

        if player.state == Player.CHOOSING:
            # Make player choice
            try:
                player.choose(choices)
            except InvalidChoiceError as e:
                cardinal.sendMsg(channel, e.message)
                return
            except InvalidMoveError:
                pass

            # Check if game transitioned
            if self.game.state == Game.WAITING_PICK:
                self.show_choices()
            else:
                choosing = []
                for _, p in self.game.players.items():
                    if p.state == Player.CHOOSING:
                        choosing.append(p.name)

                cardinal.sendMsg(self.channel,
                                 "{} has chosen. Still choosing: {}"
                                 .format(player.name, ', '.join(choosing)))

        elif player.state == Player.PICKING:
            # Make sure they aren't flubbing the command
            if len(choices) > 1:
                cardinal.sendMsg(
                    channel,
                    "You may only pick one winner."
                )
                return

            # Make player pick
            try:
                player, card = self.game.pick(choices[0])
            except InvalidPickError:
                cardinal.sendMsg(channel, "Invalid pick. Please try again!")
                return
            except InvalidMoveError:
                pass

            cardinal.sendMsg(self.channel,
                             "{} won the round with '{}' Congrats! You "
                             "have {} point(s).".format(player.name,
                                                        card,
                                                        player.points))

            # Check if game transitioned, and show new choices
            if self.game.state == Game.WAITING_CHOICES:
                self.show_black_card()
                self.show_hands()

        if self.game.state == Game.OVER:
            self.finish_game()

    @command('score')
    @help("Give Cards Against Humanity score")
    @help("Syntax: .score")
    def score(self, cardinal, channel, msg):
        self.send_scores()

    @event('irc.kick')
    def _kicked(self, cardinal, kicker, channel, kicked, _):
        """Remove kicked players from the game"""
        try:
            self.remove_player(channel, kicked)
        except KeyError:
            return

    @event('irc.part')
    def _left(self, cardinal, leaver, channel, _):
        """Remove players who part from the game"""
        try:
            self.remove_player(channel, leaver.nick)
        except KeyError:
            return

    @event('irc.quit')
    def _quit(self, cardinal, quitter, _):
        """Remove players who quit from the game"""
        for channel, _ in self.games.items():
            try:
                self.remove_player(channel, quitter.nick)
            except KeyError:
                return

    def remove_player(self, player):
        """Removes a player from a channel's game.

        Raises:
          KeyError -- If a game or player doesn't exist.
        """
        if not self.game:
            return

        initial_state = self.game.state

        self.game.remove_player(player)
        self.cardinal.sendMsg(self.channel, "{} left the game!".format(player))

        # if game went from waiting pick to waiting choices, then this player
        # was the card czar.
        if (initial_state == Game.WAITING_PICK and
                self.game.state == Game.WAITING_CHOICES):
            self.cardinal.sendMsg(self.channel,
                                  "Round skipped since {} was supposed to "
                                  "pick a winner.".format(player))

            self.show_black_card()
            self.show_hands()

        # if this was the last player we were waiting on for a choice, then
        # move on to having the card czar pick
        elif (initial_state == Game.WAITING_CHOICES and
                self.game.state == Game.WAITING_PICK):
            self.show_choices()

        # otherwise, if we ran out of players, end the game...
        elif self.game.state == Game.OVER:
            self.cardinal.sendMsg(self.channel,
                                  "The game has ended due to lack of players.")
            self.finish_game()

    def show_hands(self):
        if not self.game:
            return

        for nick, player in self.game.players.items():
            if player.state == Player.WAITING:
                self.cardinal.sendMsg(nick, "You are picking this round.")
                continue

            hand = []

            # Instructions
            syntax = ['<choice>' for _ in range(self.game.required_cards)]
            syntax.insert(0, '.choose')
            self.cardinal.sendMsg(nick,
                                  "Use {} to make your {}.".format(
                                      ' '.join(syntax),
                                      ('choices'
                                       if len(syntax) > 2
                                       else 'choice'),
                                  ))

            # Hand
            for idx, card in enumerate(player.hand):
                hand.append("[{}] {}".format(idx, card))
            self.cardinal.sendMsg(nick, "Hand: {}".format(' '.join(hand)))

            # Prompt (black card)
            self.cardinal.sendMsg(nick,
                                  "Black card: {} | Player picking: {}"
                                  .format(
                                        self.game.black_card.replace(
                                            '%s', '____'),
                                        self.game.picker.name,
                                  ))

    def show_black_card(self):
        if not self.game:
            return

        self.cardinal.sendMsg(self.channel,
                              "Black card: {} | Player picking: {}"
                              .format(
                                    self.game.black_card.replace('%s', '____'),
                                    self.game.picker.name,
                              ))

    def show_choices(self):
        if not self.game:
            return

        # No blanks, show prompt
        if '%s' not in self.game.black_card:
            self.cardinal.sendMsg(self.channel, self.game.black_card)

        for idx, choice in enumerate(self.game.choices):
            # Send the option
            self.cardinal.sendMsg(self.channel,
                                  " [{}] {}".format(idx, choice[1]))

        self.cardinal.sendMsg(self.channel,
                              "{}: Make your choice with .choose!"
                              .format(self.game.picker.name))

    def send_scores(self):
        if not self.game:
            return

        standing = 0
        for name, player in self.game.scores:
            standing += 1
            self.cardinal.sendMsg(self.channel,
                                  "{}. {} - {} points"
                                  .format(standing, name, player.points))

    def finish_game(self):
        if not self.game:
            return

        # log but continue ending the game if scores fail to send
        try:
            self.send_scores()
        except Exception:
            self.logger.exception("Failure sending scores")
            self.cardinal.sendMsg(self.channel,
                                  "I had an issue tallying up scores. :(")

        # Close the game cleanly - still let a new game begin if this fails for
        # some reason
        try:
            self.game.close()
        finally:
            self.game = None

            self.cardinal.sendMsg(self.channel,
                                  "Well played! You may use .play to start a "
                                  "new game.")

    def close(self, cardinal):
        if self.game:
            self.game.close()


def setup(cardinal, config):
    return CAHPlugin(cardinal, config)


# Begin game code


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
        self.play_deque.remove(player)

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


def load_decks():
    logger = logging.getLogger(__name__)

    decks_dir = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        'decks',
    )
    logger.info("Looking for decks in: {}".format(decks_dir))

    try:
        potential_decks = [d for d in os.listdir(decks_dir)
                           if os.path.isdir(os.path.join(decks_dir, d))]
    except FileNotFoundError:
        logger.warning("decks directory does not exist: {}".format(decks_dir))
        potential_decks = []

    logger.info("Found potential decks: {}".format(potential_decks))

    decks = {}

    for deck in potential_decks:
        deck_dir = os.path.join(decks_dir, deck)
        files = glob(os.path.join(deck_dir, '*.txt'))

        logger.info("Looking at deck {}: {}".format(deck, deck_dir))

        black_path = os.path.join(deck_dir, 'black.txt')
        white_path = os.path.join(deck_dir, 'black.txt')
        desc_path = os.path.join(deck_dir, 'desc.txt')

        if white_path in files and black_path in files:
            logger.info("Deck has white & black files: {}".format(deck))
            description = "(no description)"
            with open(os.path.join(deck_dir, 'black.txt'), 'r') as black, \
                    open(os.path.join(deck_dir, 'white.txt'), 'r') as white:
                decks[deck] = {
                    'black': black.read().strip().split("\n"),
                    'white': white.read().strip().split("\n"),
                    'description': description,
                }

            if desc_path in files:
                with open(os.path.join(deck_dir, 'desc.txt'), 'r') as desc:
                    decks[deck]['description'] = desc.read().strip()

            logging.info("Deck {} loaded: {}".format(
                deck, decks[deck]['description']))

    return decks
