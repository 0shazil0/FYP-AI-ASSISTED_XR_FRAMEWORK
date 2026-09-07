using UnityEngine;
using NeuroGuideXR.AR;
using NeuroGuideXR.Networking;

namespace NeuroGuideXR.Core
{
    public sealed class NeuroGuideController : MonoBehaviour
    {
        [SerializeField] private WebSocketManager webSocketManager;
        [SerializeField] private AROverlayManager overlayManager;

        private void Awake()
        {
            if (webSocketManager == null)
            {
                webSocketManager = FindFirstObjectByType<WebSocketManager>();
            }

            if (overlayManager == null)
            {
                overlayManager = FindFirstObjectByType<AROverlayManager>();
            }
        }

        private void Start()
        {
            Debug.Log("NeuroGuideController initialized.");
            if (webSocketManager == null)
            {
                Debug.LogWarning("WebSocketManager missing in scene.");
            }

            if (overlayManager == null)
            {
                Debug.LogWarning("AROverlayManager missing in scene.");
            }
        }
    }
}
