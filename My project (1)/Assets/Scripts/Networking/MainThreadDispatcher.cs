using System;
using System.Collections.Concurrent;
using UnityEngine;

namespace NeuroGuideXR.Networking
{
    public sealed class MainThreadDispatcher : MonoBehaviour
    {
        private static readonly ConcurrentQueue<Action> Queue = new();
        private static MainThreadDispatcher _instance;

        public static bool IsReady => _instance != null;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void Bootstrap()
        {
            if (_instance != null)
            {
                return;
            }

            var go = new GameObject("MainThreadDispatcher");
            DontDestroyOnLoad(go);
            _instance = go.AddComponent<MainThreadDispatcher>();
        }

        public static void EnsureExists()
        {
            if (_instance == null)
            {
                Bootstrap();
            }
        }

        public static void Enqueue(Action action)
        {
            if (action == null)
            {
                return;
            }

            EnsureExists();

            Queue.Enqueue(action);
        }

        private void Update()
        {
            while (Queue.TryDequeue(out var action))
            {
                try
                {
                    action.Invoke();
                }
                catch (Exception exception)
                {
                    Debug.LogError($"MainThreadDispatcher action failed: {exception.Message}");
                }
            }
        }
    }
}
