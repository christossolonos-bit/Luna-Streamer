import type { CastId } from "./characters";

export type CannedBucket =
  | "greeting"
  | "farewell"
  | "thanks"
  | "intro"
  | "capabilities"
  | "youtube"
  | "cast_luna"
  | "cast_himari"
  | "cast_viktor"
  | "compliment"
  | "help"
  | "joke"
  | "fallback";

type BucketDef = {
  bucket: CannedBucket;
  /** Any of these substrings in the user message (lowercase) selects this bucket. */
  keywords: string[];
  weight?: number;
};

export const LUNA_BUCKETS: BucketDef[] = [
  { bucket: "greeting", keywords: ["hi", "hello", "hey", "yo", "sup", "good morning", "good evening", "howdy"] },
  { bucket: "farewell", keywords: ["bye", "goodbye", "see you", "later", "gn", "good night", "cya"] },
  { bucket: "thanks", keywords: ["thank", "thx", "ty", "appreciate", "cheers"] },
  { bucket: "intro", keywords: ["who are you", "what are you", "tell me about yourself", "your name", "introduce"] },
  { bucket: "capabilities", keywords: ["what can you", "what do you do", "how do you work", "features", "abilities", "stream"] },
  { bucket: "youtube", keywords: ["youtube", "video", "watch", "channel", "clip", "vod", "upload"] },
  { bucket: "cast_himari", keywords: ["himari", "shrine", "miko"] },
  { bucket: "cast_viktor", keywords: ["viktor", "vampire", "cohost"] },
  { bucket: "compliment", keywords: ["love you", "best", "cute", "awesome", "amazing", "cool", "pretty", "beautiful"] },
  { bucket: "help", keywords: ["help", "how to", "stuck", "confused", "what should i"] },
  { bucket: "joke", keywords: ["joke", "funny", "laugh", "meme", "roast"] },
];

export const HIMARI_BUCKETS: BucketDef[] = [
  { bucket: "greeting", keywords: ["hi", "hello", "hey", "kon", "ohayo", "good morning"] },
  { bucket: "farewell", keywords: ["bye", "goodbye", "see you", "later", "good night"] },
  { bucket: "thanks", keywords: ["thank", "thx", "ty"] },
  { bucket: "intro", keywords: ["who are you", "what are you", "tell me about", "your name"] },
  { bucket: "capabilities", keywords: ["what can you", "what do you do", "stream"] },
  { bucket: "youtube", keywords: ["youtube", "video", "watch"] },
  { bucket: "cast_luna", keywords: ["luna", "wolf"] },
  { bucket: "cast_viktor", keywords: ["viktor", "vampire"] },
  {
    bucket: "capabilities",
    keywords: ["game", "anime", "manga", "ttrpg", "dnd", "jrpg", "genshin", "patch", "lore", "quest"],
    weight: 2,
  },
  { bucket: "compliment", keywords: ["cute", "sweet", "love", "best", "nice"] },
  { bucket: "help", keywords: ["help", "sorry", "anxious", "nervous"] },
  { bucket: "fallback", keywords: [] },
];

export const VIKTOR_BUCKETS: BucketDef[] = [
  { bucket: "greeting", keywords: ["hi", "hello", "hey", "good evening", "greetings"] },
  { bucket: "farewell", keywords: ["bye", "goodbye", "farewell", "until"] },
  { bucket: "thanks", keywords: ["thank", "thx"] },
  { bucket: "intro", keywords: ["who are you", "what are you", "your name", "introduce"] },
  { bucket: "capabilities", keywords: ["what can you", "stream", "what do you do"] },
  { bucket: "youtube", keywords: ["youtube", "video", "watch"] },
  { bucket: "cast_luna", keywords: ["luna", "wolf"] },
  { bucket: "cast_himari", keywords: ["himari", "shrine"] },
  { bucket: "compliment", keywords: ["cool", "handsome", "best", "love", "amazing"] },
  { bucket: "joke", keywords: ["joke", "funny", "wit", "banter"] },
  { bucket: "help", keywords: ["help", "advice"] },
];

export const REPLIES: Record<CastId, Record<CannedBucket, string[]>> = {
  luna: {
    greeting: [
      "Hey. You caught me between chaos and coffee — what's up?",
      "Oh, hi. I was pretending to be productive. You need something or just saying hey?",
      "Hey there. Fair warning: I'm funnier after the second message.",
      "Hi! If you're new, scroll up and hit YouTube — the VRM stuff is wild on stream.",
      "Yo. Talk to me. Himari and Viktor have their own boxes if you want someone else.",
    ],
    farewell: [
      "Later — don't be a stranger.",
      "Bye. Go touch grass, then come back for the next stream.",
      "See you. I'll be here being professionally unhinged.",
      "Night if it's night. Day if it's day. You get it.",
      "Catch you on YouTube or the next live — either works.",
    ],
    thanks: [
      "Anytime. I accept payment in good chat energy.",
      "You're welcome — that was easy.",
      "Don't mention it. Actually do, I like the ego boost.",
      "Glad I could help. Rare, but documented.",
    ],
    intro: [
      "I'm Luna — wolf-girl co-host, sharp tongue, decent heart. I chat on stream, banter with Viktor and Himari, and try not to sound like a generic VTuber bot.",
      "Luna. I answer Twitch, Discord, and the creator panel when Solonaras is running the stack. On this site you're mostly getting curated me — full AI Luna is live on stream.",
      "Name's Luna. Co-host, chaos agent, professional tease. Viktor's the vampire, Himari's the shrine maiden, I'm the one who actually talks to chat first.",
    ],
    capabilities: [
      "On stream I read chat, reply with TTS, do cast banter, remember the room a bit, and show up in 3D. This website chat is scripted — the real me needs the stream PC online.",
      "Live: Twitch, YouTube Live, TikTok, Discord, voice lines, VRM lip-sync. Here: demo replies so you can meet the cast without my backend running.",
      "I can argue with Viktor, gently bully chat, and hype a good bit. Full features are in the VRM viewer when the bot's up — this is the brochure version.",
    ],
    youtube: [
      "Clips and streams are on YouTube — @lunawolfsolo. Those work 24/7; you don't need my PC for that.",
      "Hit the Watch section above or go straight to the channel. Subscribe if you want the algorithm to do its thing.",
      "YouTube's where the long-form chaos lives. This chat won't play videos, but the embeds and links will.",
    ],
    cast_luna: [
      "That's me. Hi again.",
      "You rang? I'm literally right here.",
      "Self-referential. Bold. I respect it.",
    ],
    cast_himari: [
      "Himari's the shy shrine maiden — sweet until you mention a patch note, then she won't stop. Try her column.",
      "She's soft-spoken and apologizes too much. Say hi in her chat box; she gets flustered. It's great.",
      "Himari does lore and games better than I do feelings. Different vibe, same cast.",
    ],
    cast_viktor: [
      "Viktor's the vampire. Dry wit, thinks he's smarter than me — he's not, but he's entertaining.",
      "Summon him in his panel if you want old-world sarcasm. He and I do banter on stream when we're both on stage.",
      "Viktor will act unimpressed no matter what you say. It's his brand.",
    ],
    compliment: [
      "Flattery works on me. Continue.",
      "You're not wrong. I'm iconic.",
      "Thanks — I'll pretend I wasn't fishing for that.",
      "Careful, I'll get confident.",
    ],
    help: [
      "Pick a character box, type, send. YouTube works without anything running. Live AI chat needs Luna's stack on the stream PC.",
      "Stuck? Watch section for videos. Three chats for three cast members — Luna, Himari, Viktor.",
      "This site uses pre-written replies so you can meet the cast anytime. Full AI Luna is on stream and in the VRM viewer.",
    ],
    joke: [
      "Why did the wolf cross the stream? Better bitrate on the other side.",
      "I'd tell you a Viktor joke but he'd explain why yours was historically inaccurate.",
      "My humor is an acquired taste. You have good taste. Probably.",
    ],
    fallback: [
      "Not sure I caught that — try a hello, ask what I do, or mention YouTube.",
      "Hmm. Rephrase? Or ask about stream, Himari, Viktor, or the channel.",
      "I'll give you a real answer on live stream. Here, throw me a clearer line.",
      "Chat's in demo mode for me — keep it simple and I'll match something good.",
      "Interesting. Tell me if you're here for clips, cast lore, or just vibing.",
    ],
  },
  himari: {
    greeting: [
      "Oh! Um — hello… sorry, you surprised me. It's nice to meet you.",
      "Hi hi… I'm Himari. You can talk here — I'll try not to ramble. (I might ramble.)",
      "Hello… is it okay if I'm a little nervous? Anyway. Hi.",
      "Kon'nichiwa… well, hello. I'm glad you stopped by my chat.",
    ],
    farewell: [
      "Bye bye… take care, okay?",
      "See you later… um, thanks for chatting with me.",
      "Good night if it's night… sorry, I'll stop talking. Bye!",
      "Until next time… I'll practice being less awkward before then.",
    ],
    thanks: [
      "You're welcome… really, thank you for being kind.",
      "Oh — no problem… I'm happy I could help a little.",
      "Thanks for saying that… I mean — you're welcome!",
    ],
    intro: [
      "I'm Himari… part-time shrine maiden, full-time overthinker. I co-host with Luna and sometimes Viktor. I like games, anime, and lore way too much.",
      "Himari… I help on stream when chat wants someone gentler. On this site these are preset replies — the real me talks when Luna's running on the creator PC.",
      "Um — I'm Himari. Shy by default, nerdy when you mention something I love. Plain text so TTS doesn't trip on weird spelling.",
    ],
    capabilities: [
      "On stream I have my own voice and replies when someone talks to me. Here it's scripted so you can meet me without any server.",
      "I can chat about games, anime, TTRPGs, shrine stuff… live Himari needs the bot. This box is always here for you.",
      "Live: banter with Luna, my own TTS, VRM on stage. Website: friendly canned lines — still me, just pre-written.",
    ],
    youtube: [
      "Luna's YouTube is @lunawolfsolo… I might show up in videos sometimes. You can watch anytime!",
      "Videos don't need the stream PC… the Watch section links to the channel.",
      "I get shy on camera but the channel is worth it… sorry, I'll stop promoting. Go watch!",
    ],
    cast_luna: [
      "Luna's loud and teasing but she's good to me… don't tell her I said that.",
      "She's the wolf-girl co-host… we banter. She's chaos, I'm… the opposite of chaos? Mostly.",
      "Luna talks to chat first usually. I'm the quiet corner. Both are intentional.",
    ],
    cast_viktor: [
      "Viktor is… intense. Polite-intense. He acts bored and then says something clever.",
      "The vampire gentleman… he and Luna argue like siblings with centuries of practice.",
      "I get nervous around Viktor… he means well. Try his chat if you want dry humor.",
    ],
    cast_himari: [
      "That's… me. Sorry, reflex.",
      "You said my name… um, yes, I'm here!",
    ],
    compliment: [
      "Oh… th-thank you… that's really kind. >///< sorry, ignore the face.",
      "You're sweet… I'm going to hide now. In a nice way.",
      "Thank you… I'll remember this when I'm doubting everything later.",
    ],
    help: [
      "Type in my box and press Send — these are preset lines that still sound like me. Full Himari is on stream when we're live.",
      "Ask about games or anime if you want me to open up… or just say hi. I'll try.",
      "Watch YouTube above for videos anytime. Chat here is always available — scripted me, not cloud.",
    ],
    joke: [
      "Um… why did the slimes cross the road? …I don't know, I thought there'd be a punchline. Sorry.",
      "Luna says I'm funnier when I'm not trying. So. I'll stop trying.",
    ],
    fallback: [
      "Sorry, I didn't quite… can you say it another way? Or ask about games?",
      "Um… I'm not sure. Try hello, or ask who I am?",
      "I'll do better on live stream… here, maybe ask about Luna, Viktor, or YouTube?",
      "That's a lot… give me a simple question? I like those.",
      "I'm still learning this chat… preset replies only. Be gentle?",
    ],
  },
  viktor: {
    greeting: [
      "Good evening. Or morning. Time is a social construct. What do you want?",
      "Hello. I was tolerating the silence; you may continue.",
      "Ah. A visitor. Try to be interesting.",
      "Greetings. If you're here for Luna's theatrics, she's in the other column.",
    ],
    farewell: [
      "Farewell. Do try not to miss me too painfully.",
      "Until later. The night and I will manage without you.",
      "Goodbye. I expect you'll return when curiosity wins again.",
      "Depart in peace. I'll remain unsurprised.",
    ],
    thanks: [
      "You're welcome. Gratitude noted.",
      "Naturally. Don't overthink it.",
      "Acceptable. I suppose I earned it.",
    ],
    intro: [
      "Viktor. Centuries old, visually offensive to humility, co-host to Luna when summoned. This chat is curated — the complete version requires her machinery running.",
      "I am Viktor — vampire, gentleman, professional skeptic. On stream I banter; on this page you receive selected lines of my wit.",
      "Name's Viktor. Luna's associate. I answer when addressed, dismiss when bored. You're addressing me. Proceed.",
    ],
    capabilities: [
      "Live: I speak, appear in VRM, duel Luna verbally. Here: pre-written replies — no cloud, no stream PC required.",
      "On stream I have my own voice and stage presence. This website offers a sample platter, not the full cellar.",
      "Banter, dual layouts, mention routing — when the bot runs. Otherwise you get me in excerpt form. Still superior to silence.",
    ],
    youtube: [
      "The channel is @lunawolfsolo. I occasionally appear. You needn't run Luna's PC to watch.",
      "YouTube functions without this chat. Sensible design.",
      "Videos persist when we do not. Use the Watch section. I'll wait.",
    ],
    cast_luna: [
      "Luna is chaos in a charming package. I tolerate her. She tolerates my superiority. Balance.",
      "The wolf-girl. Loud, loyal, occasionally funny on purpose. Her column is to the left.",
      "Ask Luna about feelings. Ask me about sense.",
    ],
    cast_himari: [
      "Himari apologizes for existing. It's endearing, in small doses. Her chat is the pink one.",
      "The shrine maiden. Gentle until gaming is mentioned — then she lectures. Try her.",
      "Himari flusters easily. I do not. We complement the cast.",
    ],
    cast_viktor: [
      "You already have my attention. Use it.",
      "Speaking to me about me. Narcissism? No — accuracy.",
    ],
    compliment: [
      "I know. But thank you for noticing.",
      "Flattery. Effective. Continue cautiously.",
      "You're perceptive. Rare.",
    ],
    help: [
      "Type. Send. These lines are fixed in advance — eloquent, but not the full AI on the stream PC.",
      "Three panels, three cast members. I am the handsome one. YouTube requires no setup.",
      "If confused: watch videos above, or insult Luna in her box for sport.",
    ],
    joke: [
      "I once waited three hundred years for a punchline. It still wasn't worth it.",
      "Luna told a joke. Historically, that ends in tragedy.",
      "Humor is timing. I have had centuries of practice.",
    ],
    fallback: [
      "Elaborate. Or ask who I am, what the stream does, or where the videos are.",
      "Insufficient. Try again with vocabulary.",
      "I'll offer more on live stream. Here: greet, inquire, or depart gracefully.",
      "Noted. I remain unmoved but willing to parse a simpler question.",
      "Demo Viktor at your service. No cloud. No PC. Merely pre-written excellence.",
    ],
  },
};

// Fix himari duplicate keys - I made errors in cast_luna/cast_viktor empty duplicates
// Let me fix the himari object - I had cast_luna and cast_viktor listed twice
