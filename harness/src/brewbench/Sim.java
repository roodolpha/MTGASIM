package brewbench;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import com.google.common.eventbus.Subscribe;

import forge.GuiDesktop;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.game.*;
import forge.game.card.Card;
import forge.game.event.GameEvent;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;
import forge.game.player.RegisteredPlayer;
import forge.game.zone.ZoneType;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.player.GamePlayerUtil;
import forge.view.TimeLimitedCodeBlock;

/**
 * Plays AI-vs-AI games in Forge and writes one JSON line per game.
 *
 * Usage: Sim &lt;format&gt; &lt;deckA.dck&gt; &lt;deckB.dck&gt; &lt;games&gt; &lt;out.jsonl&gt; [timeoutSecs] [seed]
 *   format: brawl | constructed
 *
 * Each line: {"result":"Win|Loss|Draw|Error","first":"a|b","ms":..,"turns":..,"deck_b":"file.dck",
 *             "life":{"a":..,"b":..},"states":[...]}
 * "result" is from deck A's point of view. "states" holds the board at the end of every turn.
 *
 * This file is part of Brewbench and is licensed under the GNU GPL v3 (it links against Forge, also GPL v3).
 */
public final class Sim {
    private static String q(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c < 32) b.append(' ');
            else b.append(c);
        }
        return b.append('"').toString();
    }

    private static String side(Player p) {
        StringBuilder b = new StringBuilder();
        b.append("{\"life\":").append(p.getLife())
         .append(",\"hand\":").append(p.getCardsIn(ZoneType.Hand).size())
         .append(",\"lib\":").append(p.getCardsIn(ZoneType.Library).size())
         .append(",\"poison\":").append(p.getPoisonCounters())
         .append(",\"perms\":[");
        boolean first = true;
        for (Card c : p.getCardsIn(ZoneType.Battlefield)) {
            if (!first) b.append(',');
            first = false;
            boolean cre = c.isCreature();
            b.append('[').append(q(c.getName())).append(',')
             .append(cre ? String.valueOf(c.getNetPower()) : "null").append(',')
             .append(cre ? String.valueOf(c.getNetToughness()) : "null").append(',')
             .append(c.isTapped() ? 1 : 0).append(',')
             .append(c.isLand() ? 1 : 0).append(',')
             .append(c.isToken() ? 1 : 0).append(']');
        }
        return b.append("]}").toString();
    }

    private static Player byName(Game game, String name) {
        // registered players: includes a player who has already lost and left the game
        for (Player p : game.getRegisteredPlayers()) if (p.getName().equals(name)) return p;
        return null;
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 5) {
            System.err.println("Usage: Sim <brawl|constructed> <deckA.dck> <deckB.dck> <games> <out.jsonl> [timeoutSecs] [seed]");
            System.exit(1);
        }
        System.setProperty("java.awt.headless", "true");
        final String format = args[0].toLowerCase(Locale.ROOT);
        final boolean brawl = format.equals("brawl");
        final int games = Integer.parseInt(args[3]);
        final int timeout = args.length > 5 ? Integer.parseInt(args[5]) : 180;
        if (args.length > 6) {
            // Forge shuffles through its own RNG; seeding makes paired comparisons (same seed, two decks) possible
            forge.util.MyRandom.setRandom(new Random(Long.parseLong(args[6])));
        }

        GuiBase.setInterface(new GuiDesktop());
        FModel.initialize(null, null);
        final Deck a = DeckSerializer.fromFile(new File(args[1]));
        final Deck b = DeckSerializer.fromFile(new File(args[2]));
        if (a == null || b == null) {
            System.out.println("DECK_ERROR");
            System.exit(2);
        }

        GameType type = brawl ? GameType.Brawl : GameType.Constructed;
        GameRules rules = new GameRules(type);
        if (brawl) rules.setAppliedVariants(EnumSet.of(GameType.Brawl));
        rules.setSimTimeout(timeout);

        List<RegisteredPlayer> players = new ArrayList<>();
        Deck[] decks = {a, b};
        String[] names = {"a", "b"};
        for (int i = 0; i < 2; i++) {
            RegisteredPlayer rp = brawl
                    ? RegisteredPlayer.forVariants(2, EnumSet.of(GameType.Brawl), decks[i], null, false, null, null)
                    : new RegisteredPlayer(decks[i]);
            rp.setPlayer(GamePlayerUtil.createAiPlayer(names[i], i, ""));
            players.add(rp);
        }
        Match match = new Match(rules, players, "Brewbench");
        final String deckB = new File(args[2]).getName();

        try (Writer out = new OutputStreamWriter(new FileOutputStream(args[4], true), StandardCharsets.UTF_8)) {
            for (int g = 0; g < games; g++) {
                final Game game = match.createGame();
                game.setNoGUIUser();
                final List<String> states = Collections.synchronizedList(new ArrayList<>());
                final String[] firstPlayer = {null};
                final int[] lastTurn = {0};
                game.subscribeToEvents(new Object() {
                    @Subscribe
                    public void on(GameEvent ev) {
                        if (ev instanceof GameEventTurnBegan tb) {
                            Player pa = byName(game, "a"), pb = byName(game, "b");
                            if (pa == null || pb == null) return;
                            String active = tb.turnOwner().toString().equals("a") ? "a" : "b";
                            if (firstPlayer[0] == null) firstPlayer[0] = active;
                            lastTurn[0] = tb.turnNumber();
                            if (tb.turnNumber() > 1) {
                                states.add("{\"t\":" + (tb.turnNumber() - 1) + ",\"next\":" + q(active)
                                        + ",\"a\":" + side(pa) + ",\"b\":" + side(pb) + "}");
                            }
                        }
                    }
                });
                String result;
                long t0 = System.currentTimeMillis();
                try {
                    TimeLimitedCodeBlock.runWithTimeout(() -> match.startGame(game), timeout, TimeUnit.SECONDS);
                    GameOutcome o = game.getOutcome();
                    if (o == null || o.isDraw()) result = "Draw";
                    else result = o.getWinningLobbyPlayer().getName().equals("a") ? "Win" : "Loss";
                } catch (TimeoutException e) {
                    result = "Draw";
                } catch (Throwable e) {
                    result = "Error";
                } finally {
                    game.setGameOver(GameEndReason.Draw);
                }
                Player pa = byName(game, "a"), pb = byName(game, "b");
                String life = (pa != null && pb != null)
                        ? ",\"life\":{\"a\":" + pa.getLife() + ",\"b\":" + pb.getLife() + "}" : "";
                out.write("{\"result\":" + q(result) + ",\"first\":" + q(String.valueOf(firstPlayer[0]))
                        + ",\"ms\":" + (System.currentTimeMillis() - t0) + ",\"turns\":" + lastTurn[0]
                        + ",\"deck_b\":" + q(deckB) + life
                        + ",\"states\":[" + String.join(",", states) + "]}\n");
                out.flush();
                System.out.println("GAME_DONE " + result);
                System.out.flush();
            }
        }
        System.exit(0);
    }
}
