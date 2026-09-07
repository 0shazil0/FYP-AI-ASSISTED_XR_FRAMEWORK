// Assets/Scripts/Core/VoiceInputManager.cs
// ==========================================
// Wraps Android's SpeechRecognizer API to provide voice-to-text input.
// Dispatches the recognized text as an event; CopilotStepController
// auto-submits it as a query (no button press needed).
//
// SETUP:
//   1. Attach this script to a persistent GameObject (e.g. NeuroGuideController).
//   2. Ensure AndroidManifest.xml has RECORD_AUDIO permission.
//   3. Call StartListening() from your mic button handler.
//   4. Subscribe to OnResultReceived to get the recognized text.
//
// PLATFORM:
//   Full functionality on Android only.
//   In the Editor, use SimulateResult() to inject test phrases.

using System;
using UnityEngine;

#if UNITY_ANDROID && !UNITY_EDITOR
using UnityEngine.Android;
#endif

namespace NeuroGuideXR.Core
{
    /// <summary>
    /// Wraps Android SpeechRecognizer for hands-free voice query input.
    /// </summary>
    public sealed class VoiceInputManager : MonoBehaviour
    {
        // ----------------------------------------------------------------
        // Inspector
        // ----------------------------------------------------------------
        [Header("Voice Settings")]
        [Tooltip("BCP-47 language tag for recognition (e.g. 'en-US').")]
        [SerializeField] private string language = "en-US";

        [Tooltip("Maximum number of recognition results to consider.")]
        [SerializeField] private int maxResults = 1;

        [Tooltip("Show partial results in status label before final commit.")]
        [SerializeField] private bool showPartialResults = true;

        // ----------------------------------------------------------------
        // Events
        // ----------------------------------------------------------------
        /// <summary>
        /// Fired when speech recognition returns a final result.
        /// Arg: recognized text string.
        /// </summary>
        public event Action<string> OnResultReceived;

        /// <summary>
        /// Fired when recognition starts (mic is active).
        /// </summary>
        public event Action OnListeningStarted;

        /// <summary>
        /// Fired when recognition ends (either result or error).
        /// </summary>
        public event Action OnListeningStopped;

        /// <summary>
        /// Fired with a partial transcript while the user is still speaking.
        /// </summary>
        public event Action<string> OnPartialResult;

        // ----------------------------------------------------------------
        // State
        // ----------------------------------------------------------------
        private bool _isListening = false;

        // Android plugin references
#if UNITY_ANDROID && !UNITY_EDITOR
        private AndroidJavaObject _unityActivity;
        private AndroidJavaObject _speechRecognizer;
        private RecognitionListenerProxy _listener;
        private bool _javaAvailable = false;
#endif

        // ----------------------------------------------------------------
        // Properties
        // ----------------------------------------------------------------
        public bool IsListening => _isListening;

        // ----------------------------------------------------------------
        // Lifecycle
        // ----------------------------------------------------------------
        private void Awake()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            InitAndroidSpeech();
#else
            Debug.Log("[VoiceInput] Editor/non-Android mode — use SimulateResult() for testing.");
#endif
        }

        private void OnDestroy()
        {
            StopListening();
        }

        // ----------------------------------------------------------------
        // Public API
        // ----------------------------------------------------------------

        /// <summary>Start voice recognition. Mic opens immediately.</summary>
        public void StartListening()
        {
            if (_isListening) return;

#if UNITY_ANDROID && !UNITY_EDITOR
            if (!HasMicPermission())
            {
                RequestMicPermission();
                return;
            }
            StartAndroidListening();
#else
            // Editor: emit event to allow testing flow without a mic
            Debug.Log("[VoiceInput] Editor — StartListening() called. Use SimulateResult(text) to inject.");
            _isListening = true;
            OnListeningStarted?.Invoke();
#endif
        }

        /// <summary>Stop recognition early (e.g. user taps mic button again).</summary>
        public void StopListening()
        {
            if (!_isListening) return;
            _isListening = false;

#if UNITY_ANDROID && !UNITY_EDITOR
            if (_speechRecognizer != null)
            {
                _unityActivity.Call("runOnUiThread", new UnityEngine.AndroidJavaRunnable(() => {
                    try { _speechRecognizer.Call("stopListening"); }
                    catch (Exception e) { Debug.LogWarning($"[VoiceInput] stopListening error: {e.Message}"); }
                }));
            }
#endif
            OnListeningStopped?.Invoke();
        }

        /// <summary>
        /// Editor/test helper: inject a fake recognition result.
        /// Useful for testing the full copilot flow in Play mode.
        /// </summary>
        public void SimulateResult(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return;
            Debug.Log($"[VoiceInput] Simulated result: '{text}'");
            _isListening = false;
            OnListeningStopped?.Invoke();
            OnResultReceived?.Invoke(text.Trim());
        }

        // ----------------------------------------------------------------
        // Android implementation
        // ----------------------------------------------------------------
#if UNITY_ANDROID && !UNITY_EDITOR
        private void InitAndroidSpeech()
        {
            try
            {
                // Get the Unity player activity
                using var player = new AndroidJavaClass("com.unity3d.player.UnityPlayer");
                _unityActivity = player.GetStatic<AndroidJavaObject>("currentActivity");

                UnityMainThreadDispatcher.Enqueue(() => {
                    try
                    {
                        using var recognizerClass = new AndroidJavaClass("android.speech.SpeechRecognizer");
                        
                        _unityActivity.Call("runOnUiThread", new UnityEngine.AndroidJavaRunnable(() => {
                            try
                            {
                                _speechRecognizer = recognizerClass.CallStatic<AndroidJavaObject>("createSpeechRecognizer", _unityActivity);
                                _listener = new RecognitionListenerProxy(this);
                                _speechRecognizer.Call("setRecognitionListener", _listener);
                                _javaAvailable = true;
                                Debug.Log("[VoiceInput] Pure C# Android SpeechRecognizer initialized.");
                            }
                            catch (Exception ex)
                            {
                                Debug.LogError($"[VoiceInput] runOnUiThread init error: {ex.Message}");
                            }
                        }));
                    }
                    catch (Exception ex)
                    {
                        Debug.LogError($"[VoiceInput] runOnUiThread setup error: {ex.Message}");
                    }
                });
            }
            catch (Exception e)
            {
                Debug.LogError($"[VoiceInput] Android init failed: {e.Message}");
            }
        }

        private void StartAndroidListening()
        {
            _isListening = true;
            OnListeningStarted?.Invoke();

            if (_javaAvailable && _speechRecognizer != null)
            {
                _unityActivity.Call("runOnUiThread", new UnityEngine.AndroidJavaRunnable(() => {
                    try
                    {
                        using var intentClass = new AndroidJavaClass("android.speech.RecognizerIntent");
                        using var intent = new AndroidJavaObject("android.content.Intent",
                                             intentClass.GetStatic<string>("ACTION_RECOGNIZE_SPEECH"));

                        intent.Call<AndroidJavaObject>("putExtra",
                            intentClass.GetStatic<string>("EXTRA_LANGUAGE_MODEL"),
                            intentClass.GetStatic<string>("LANGUAGE_MODEL_FREE_FORM"));
                        intent.Call<AndroidJavaObject>("putExtra",
                            intentClass.GetStatic<string>("EXTRA_LANGUAGE"), language);
                        intent.Call<AndroidJavaObject>("putExtra",
                            intentClass.GetStatic<string>("EXTRA_MAX_RESULTS"), maxResults);
                        intent.Call<AndroidJavaObject>("putExtra",
                            intentClass.GetStatic<string>("EXTRA_PARTIAL_RESULTS"), showPartialResults);

                        _speechRecognizer.Call("startListening", intent);
                        Debug.Log("[VoiceInput] SpeechRecognizer.startListening() called.");
                    }
                    catch (Exception e)
                    {
                        Debug.LogError($"[VoiceInput] startListening error on UI thread: {e.Message}");
                        _isListening = false;
                        OnListeningStopped?.Invoke();
                    }
                }));
            }
            else
            {
                Debug.LogWarning("[VoiceInput] SpeechRecognizer not initialized, falling back to Intent STT.");
                StartIntentListening();
            }
        }

        private void StartIntentListening()
        {
            try
            {
                using var intentClass  = new AndroidJavaClass("android.speech.RecognizerIntent");
                using var intent       = new AndroidJavaObject("android.content.Intent",
                                             intentClass.GetStatic<string>("ACTION_RECOGNIZE_SPEECH"));

                intent.Call<AndroidJavaObject>("putExtra",
                    intentClass.GetStatic<string>("EXTRA_LANGUAGE_MODEL"),
                    intentClass.GetStatic<string>("LANGUAGE_MODEL_FREE_FORM"));
                intent.Call<AndroidJavaObject>("putExtra",
                    intentClass.GetStatic<string>("EXTRA_LANGUAGE"), language);
                intent.Call<AndroidJavaObject>("putExtra",
                    intentClass.GetStatic<string>("EXTRA_MAX_RESULTS"), maxResults);
                intent.Call<AndroidJavaObject>("putExtra",
                    intentClass.GetStatic<string>("EXTRA_PROMPT"), "Say your question...");

                _unityActivity?.Call("startActivityForResult", intent, 9001);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[VoiceInput] Intent STT failed: {e.Message}");
                _isListening = false;
                OnListeningStopped?.Invoke();
            }
        }

        private bool HasMicPermission()
        {
            return Permission.HasUserAuthorizedPermission(Permission.Microphone);
        }

        private void RequestMicPermission()
        {
            var callbacks = new PermissionCallbacks();
            callbacks.PermissionGranted += _ =>
            {
                Debug.Log("[VoiceInput] Microphone permission granted.");
                StartAndroidListening();
            };
            callbacks.PermissionDenied += _ =>
            {
                Debug.LogWarning("[VoiceInput] Microphone permission denied.");
            };
            Permission.RequestUserPermission(Permission.Microphone, callbacks);
        }

        private void OnSpeechResult(string text)
        {
            Debug.Log($"[VoiceInput] Result: '{text}'");
            _isListening = false;
            OnListeningStopped?.Invoke();
            OnResultReceived?.Invoke(text.Trim());
        }

        private void OnSpeechPartial(string text)
        {
            if (showPartialResults)
                OnPartialResult?.Invoke(text);
        }

        private void OnSpeechError(string errorCode)
        {
            Debug.LogWarning($"[VoiceInput] Recognition error code: {errorCode}");
            _isListening = false;
            OnListeningStopped?.Invoke();
        }

        private class RecognitionListenerProxy : AndroidJavaProxy
        {
            private readonly VoiceInputManager _manager;

            public RecognitionListenerProxy(VoiceInputManager manager) 
                : base("android.speech.RecognitionListener")
            {
                _manager = manager;
            }

            public void onReadyForSpeech(AndroidJavaObject paramsObj) { }
            public void onBeginningOfSpeech() { }
            public void onRmsChanged(float rmsdB) { }
            public void onBufferReceived(byte[] buffer) { }
            public void onEndOfSpeech() { }
            
            public void onError(int error)
            {
                UnityMainThreadDispatcher.Enqueue(() => {
                    _manager.OnSpeechError(error.ToString());
                });
            }

            public void onResults(AndroidJavaObject results)
            {
                string resultText = GetTextFromBundle(results);
                UnityMainThreadDispatcher.Enqueue(() => {
                    _manager.OnSpeechResult(resultText);
                });
            }

            public void onPartialResults(AndroidJavaObject results)
            {
                string resultText = GetTextFromBundle(results);
                UnityMainThreadDispatcher.Enqueue(() => {
                    _manager.OnSpeechPartial(resultText);
                });
            }

            public void onEvent(int eventType, AndroidJavaObject paramsObj) { }

            private string GetTextFromBundle(AndroidJavaObject bundle)
            {
                if (bundle == null) return "";
                using var key = new AndroidJavaClass("android.speech.SpeechRecognizer");
                string resultsKey = key.GetStatic<string>("RESULTS_RECOGNITION");
                using var list = bundle.Call<AndroidJavaObject>("getStringArrayList", resultsKey);
                if (list != null)
                {
                    int size = list.Call<int>("size");
                    if (size > 0)
                    {
                        return list.Call<string>("get", 0);
                    }
                }
                return "";
            }
        }
#endif
    }
}
