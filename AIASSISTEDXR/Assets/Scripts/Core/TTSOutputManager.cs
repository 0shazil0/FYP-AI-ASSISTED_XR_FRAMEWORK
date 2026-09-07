// Assets/Scripts/Core/TTSOutputManager.cs
// ==========================================
// Wraps Android's TextToSpeech API to speak coaching instructions aloud.
// CopilotStepController calls Speak(tts_text) for each step and for
// step_verification coaching feedback.
//
// SETUP:
//   1. Attach this script to a persistent GameObject (e.g. NeuroGuideController).
//   2. No permissions needed — TTS is always available on Android.
//   3. Call Speak(text) from anywhere to enqueue speech.
//
// PLATFORM:
//   Full functionality on Android only.
//   In the Editor, speech is logged to the Console for testing.

using System;
using System.Collections;
using UnityEngine;

namespace NeuroGuideXR.Core
{
    /// <summary>
    /// Wraps Android TextToSpeech for spoken AR coaching instructions.
    /// </summary>
    public sealed class TTSOutputManager : MonoBehaviour
    {
        // ----------------------------------------------------------------
        // Inspector
        // ----------------------------------------------------------------
        [Header("TTS Settings")]
        [Tooltip("BCP-47 language tag (e.g. 'en-US'). Must match a TTS voice installed on the device.")]
        [SerializeField] private string language = "en-US";

        [Tooltip("Speech rate. 1.0 = normal, 0.8 = slightly slower (clearer for instructions).")]
        [Range(0.5f, 2.0f)]
        [SerializeField] private float speechRate = 0.9f;

        [Tooltip("Pitch. 1.0 = normal.")]
        [Range(0.5f, 2.0f)]
        [SerializeField] private float pitch = 1.0f;

        [Tooltip("If true, new Speak() calls interrupt any currently speaking sentence.")]
        [SerializeField] private bool interruptOnNew = true;

        // ----------------------------------------------------------------
        // State
        // ----------------------------------------------------------------
        private bool _isInitialised = false;
        private bool _isSpeaking    = false;

        // Event
        /// <summary>Fired when TTS finishes speaking an utterance.</summary>
        public event Action OnSpeechFinished;

        // Properties
        public bool IsSpeaking    => _isSpeaking;
        public bool IsInitialised => _isInitialised;

#if UNITY_ANDROID && !UNITY_EDITOR
        private AndroidJavaObject _tts;
        private AndroidJavaObject _locale;
#endif

        // ----------------------------------------------------------------
        // Lifecycle
        // ----------------------------------------------------------------
        private void Awake()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            InitAndroidTTS();
#else
            _isInitialised = true;
            Debug.Log("[TTS] Editor mode — speech will be logged to console.");
#endif
        }

        private void OnDestroy()
        {
            Shutdown();
        }

        // ----------------------------------------------------------------
        // Public API
        // ----------------------------------------------------------------

        /// <summary>
        /// Speak the given text aloud. Thread-safe — dispatches to main thread if needed.
        /// </summary>
        /// <param name="text">Text to speak. HTML tags are stripped automatically.</param>
        public void Speak(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return;

            // Strip any residual HTML/markdown that the LLM might have left
            text = StripMarkup(text);

#if UNITY_ANDROID && !UNITY_EDITOR
            if (!_isInitialised)
            {
                // Queue speech for when TTS finishes initialising
                StartCoroutine(SpeakWhenReady(text));
                return;
            }
            SpeakAndroid(text);
#else
            // Editor fallback: log to console
            Debug.Log($"[TTS] 🔊 \"{text}\"");
            _isSpeaking = false;
            OnSpeechFinished?.Invoke();
#endif
        }

        /// <summary>Stop any currently playing speech immediately.</summary>
        public void Stop()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try { _tts?.Call<int>("stop"); }
            catch { /* ignore */ }
#endif
            _isSpeaking = false;
        }

        /// <summary>Update speech rate at runtime (takes effect on next utterance).</summary>
        public void SetSpeechRate(float rate)
        {
            speechRate = Mathf.Clamp(rate, 0.5f, 2.0f);
#if UNITY_ANDROID && !UNITY_EDITOR
            _tts?.Call<int>("setSpeechRate", speechRate);
#endif
        }

        // ----------------------------------------------------------------
        // Android implementation
        // ----------------------------------------------------------------
#if UNITY_ANDROID && !UNITY_EDITOR

        private void InitAndroidTTS()
        {
            try
            {
                using var player   = new AndroidJavaClass("com.unity3d.player.UnityPlayer");
                var activity       = player.GetStatic<AndroidJavaObject>("currentActivity");

                // Create TTS.OnInitListener via AndroidJavaProxy
                var initListener   = new TTSInitListener(OnTTSInit);

                _tts = new AndroidJavaObject(
                    "android.speech.tts.TextToSpeech",
                    activity,
                    initListener
                );
                Debug.Log("[TTS] Android TTS initialising...");
            }
            catch (Exception e)
            {
                Debug.LogError($"[TTS] Init failed: {e.Message}");
                _isInitialised = true; // allow fallback (silent)
            }
        }

        private void OnTTSInit(int status)
        {
            // status 0 = SUCCESS
            if (status == 0)
            {
                try
                {
                    // Set locale
                    var localClass = new AndroidJavaClass("java.util.Locale");
                    var parts      = language.Split('-');
                    _locale = parts.Length >= 2
                        ? new AndroidJavaObject("java.util.Locale", parts[0], parts[1])
                        : localClass.GetStatic<AndroidJavaObject>("ENGLISH");

                    int localeResult = _tts.Call<int>("setLanguage", _locale);
                    if (localeResult < 0)
                        Debug.LogWarning($"[TTS] setLanguage returned {localeResult} — voice may not be available.");

                    _tts.Call<int>("setSpeechRate", speechRate);
                    _tts.Call<int>("setPitch",      pitch);

                    _isInitialised = true;
                    Debug.Log("[TTS] Android TTS ready.");
                }
                catch (Exception e)
                {
                    Debug.LogError($"[TTS] Post-init config failed: {e.Message}");
                    _isInitialised = true;
                }
            }
            else
            {
                Debug.LogError($"[TTS] Initialisation failed with status {status}.");
                _isInitialised = true; // allow app to continue without TTS
            }
        }

        private void SpeakAndroid(string text)
        {
            if (_tts == null) return;

            try
            {
                // QUEUE_FLUSH (1) = interrupt current speech
                // QUEUE_ADD   (0) = add to end of queue
                int queueMode = interruptOnNew ? 1 : 0;

                // Android API 21+ uses speak(text, queueMode, params, utteranceId)
                using var paramsMap = new AndroidJavaObject("android.os.Bundle");
                int result = _tts.Call<int>("speak", text, queueMode, paramsMap, "ng_utt");

                if (result == 0) // SUCCESS
                {
                    _isSpeaking = true;
                }
                else
                {
                    Debug.LogWarning($"[TTS] speak() returned error: {result}");
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[TTS] speak() exception: {e.Message}");
            }
        }

        /// <summary>Java proxy for TextToSpeech.OnInitListener.</summary>
        private class TTSInitListener : AndroidJavaProxy
        {
            private readonly Action<int> _callback;
            public TTSInitListener(Action<int> callback)
                : base("android.speech.tts.TextToSpeech$OnInitListener")
            {
                _callback = callback;
            }
            // Called from Java on the Android UI thread → must dispatch to Unity main thread
            void onInit(int status)
            {
                UnityMainThreadDispatcher.Enqueue(() => _callback?.Invoke(status));
            }
        }
#endif

        // ----------------------------------------------------------------
        // Helpers
        // ----------------------------------------------------------------

        private void Shutdown()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                _tts?.Call<int>("stop");
                _tts?.Call("shutdown");
                _tts?.Dispose();
                _tts = null;
            }
            catch { /* ignore */ }
#endif
        }

        private IEnumerator SpeakWhenReady(string text)
        {
            float waited = 0f;
            while (!_isInitialised && waited < 5f)
            {
                yield return null;
                waited += Time.deltaTime;
            }
            if (_isInitialised)
                Speak(text);
        }

        private static string StripMarkup(string text)
        {
            // Remove ** bold **, *italic*, and leading/trailing whitespace
            text = System.Text.RegularExpressions.Regex.Replace(text, @"\*+", "");
            return text.Trim();
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // UnityMainThreadDispatcher
    // A minimal thread-safe dispatcher to marshal Java callbacks to Unity.
    // If you already have one in your project, delete this and keep yours.
    // ─────────────────────────────────────────────────────────────────────
    public sealed class UnityMainThreadDispatcher : MonoBehaviour
    {
        private static readonly System.Collections.Generic.Queue<Action> _queue
            = new System.Collections.Generic.Queue<Action>();
        private static UnityMainThreadDispatcher _instance;

        public static void Enqueue(Action action)
        {
            lock (_queue)
            {
                _queue.Enqueue(action);
                if (_instance == null && Application.isPlaying)
                {
                    // Create dynamic dispatcher
                    var go = new GameObject("UnityMainThreadDispatcher_Dynamic");
                    _instance = go.AddComponent<UnityMainThreadDispatcher>();
                    DontDestroyOnLoad(go);
                }
            }
        }

        private void Awake()
        {
            if (_instance != null && _instance != this) { Destroy(gameObject); return; }
            _instance = this;
            DontDestroyOnLoad(gameObject);
        }

        private void Update()
        {
            while (true)
            {
                Action action;
                lock (_queue)
                {
                    if (_queue.Count == 0) break;
                    action = _queue.Dequeue();
                }
                action?.Invoke();
            }
        }
    }
}
