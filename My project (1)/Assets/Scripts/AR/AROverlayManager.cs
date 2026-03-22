using System;
using Newtonsoft.Json;
using UnityEngine;
using NeuroGuideXR.Networking;

namespace NeuroGuideXR.AR
{
    public sealed class AROverlayManager : MonoBehaviour
    {
        [SerializeField] private GameObject arrowPrefab;
        [SerializeField] private GameObject highlightPrefab;
        [SerializeField] private float defaultDistance = 1.2f;
        [SerializeField] private float minDistanceFromCamera = 1.1f;
        [SerializeField] private float maxDistanceFromCamera = 2.2f;
        [SerializeField] private float defaultOverlayScale = 0.08f;
        [SerializeField, Range(0.15f, 0.9f)] private float overlayOpacity = 0.35f;
        [SerializeField] private bool renderStepCard = true;
        [SerializeField] private Vector3 cardLocalOffset = new Vector3(0.16f, 0.14f, 0f);
        [SerializeField] private float cardScale = 0.18f;

        private GameObject _activeOverlay;
        private GameObject _activeStepCard;
        private bool _subscribed;

        private void OnEnable()
        {
            TrySubscribe();
        }

        private void Start()
        {
            TrySubscribe();
        }

        private void Update()
        {
            if (!_subscribed)
            {
                TrySubscribe();
            }
        }

        private void OnDisable()
        {
            if (WebSocketManager.Instance != null)
            {
                WebSocketManager.Instance.MessageReceived -= OnMessageReceived;
            }

            _subscribed = false;
        }

        private void TrySubscribe()
        {
            if (_subscribed || WebSocketManager.Instance == null)
            {
                return;
            }

            WebSocketManager.Instance.MessageReceived -= OnMessageReceived;
            WebSocketManager.Instance.MessageReceived += OnMessageReceived;
            _subscribed = true;
            Debug.Log("AROverlayManager subscribed to WebSocket messages");
        }

        private void OnMessageReceived(string json)
        {
            GuidanceMessage message;
            try
            {
                message = JsonConvert.DeserializeObject<GuidanceMessage>(json);
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"Guidance parse failed: {exception.Message}");
                return;
            }

            if (message == null || !ShouldRenderMessage(message))
            {
                return;
            }

            Debug.Log($"Guidance received: type={message.type}, task={message.task}, visual={message.visual_type}");
            Render(message);
        }

        private static bool ShouldRenderMessage(GuidanceMessage message)
        {
            if (message == null)
            {
                return false;
            }

            return string.Equals(message.type, "guidance", StringComparison.OrdinalIgnoreCase)
                || string.Equals(message.type, "snapshot_result", StringComparison.OrdinalIgnoreCase)
                || string.Equals(message.type, "prompt_response", StringComparison.OrdinalIgnoreCase)
                || string.Equals(message.type, "step_update", StringComparison.OrdinalIgnoreCase);
        }

        private void Render(GuidanceMessage message)
        {
            if (_activeOverlay != null)
            {
                Destroy(_activeOverlay);
            }

            if (_activeStepCard != null)
            {
                Destroy(_activeStepCard);
            }

            Camera camera = Camera.main;
            if (camera == null)
            {
                return;
            }

            Vector3 offset = message.location_3d != null && message.location_3d.Length == 3
                ? new Vector3(message.location_3d[0], message.location_3d[1], message.location_3d[2])
                : new Vector3(0f, 0f, defaultDistance);

            float zDistance = Mathf.Clamp(offset.z <= 0f ? defaultDistance : offset.z, minDistanceFromCamera, maxDistanceFromCamera);
            Vector3 worldPosition = camera.transform.position + camera.transform.forward * zDistance + camera.transform.right * offset.x + camera.transform.up * offset.y;

            GameObject prefab = ResolvePrefab(message.visual_type);
            _activeOverlay = prefab != null
                ? Instantiate(prefab, worldPosition, Quaternion.identity)
                : CreateFallback(worldPosition);

            _activeOverlay.transform.localScale = Vector3.one * defaultOverlayScale;
            _activeOverlay.transform.LookAt(camera.transform.position);
            _activeOverlay.name = "GuidanceOverlay";
            ApplyOverlayVisualTuning(_activeOverlay);

            if (renderStepCard && message.step_guidance != null)
            {
                _activeStepCard = CreateStepCard(worldPosition + cardLocalOffset, camera.transform.position, message);
            }

            Debug.Log($"Guidance overlay rendered at {worldPosition}");
        }

        private GameObject CreateStepCard(Vector3 worldPosition, Vector3 lookAtPosition, GuidanceMessage message)
        {
            var card = GameObject.CreatePrimitive(PrimitiveType.Quad);
            card.name = "StepGuidanceCard";
            card.transform.position = worldPosition;
            card.transform.localScale = new Vector3(cardScale * 1.5f, cardScale, 1f);
            card.transform.LookAt(lookAtPosition);

            var renderer = card.GetComponent<Renderer>();
            if (renderer != null)
            {
                renderer.material = new Material(Shader.Find("Standard"));
                renderer.material.color = new Color(0.05f, 0.09f, 0.14f, 0.92f);
            }

            var collider = card.GetComponent<Collider>();
            if (collider != null)
            {
                collider.enabled = false;
            }

            var textObj = new GameObject("CardText", typeof(TextMesh));
            textObj.transform.SetParent(card.transform, false);
            textObj.transform.localPosition = new Vector3(0f, 0f, 0.01f);
            textObj.transform.localRotation = Quaternion.identity;
            textObj.transform.localScale = Vector3.one * 0.06f;

            var textMesh = textObj.GetComponent<TextMesh>();
            textMesh.anchor = TextAnchor.MiddleCenter;
            textMesh.alignment = TextAlignment.Center;
            textMesh.fontSize = 56;
            textMesh.characterSize = 0.08f;
            textMesh.color = new Color(0.92f, 0.97f, 1f, 1f);
            textMesh.text = BuildCardText(message);

            return card;
        }

        private string BuildCardText(GuidanceMessage message)
        {
            if (message.step_guidance == null)
            {
                return message.instruction_text ?? "Guidance";
            }

            string title = string.IsNullOrWhiteSpace(message.step_guidance.recipe_title)
                ? "Live Guidance"
                : message.step_guidance.recipe_title;

            int current = Mathf.Max(1, message.step_guidance.current_step);
            int total = Mathf.Max(current, message.step_guidance.total_steps);

            string instruction = message.instruction_text;
            if (message.step_guidance.steps != null && message.step_guidance.steps.Length >= current)
            {
                var step = message.step_guidance.steps[current - 1];
                if (!string.IsNullOrWhiteSpace(step.instruction))
                {
                    instruction = step.instruction;
                }
            }

            if (string.IsNullOrWhiteSpace(instruction))
            {
                instruction = "Follow the highlighted step.";
            }

            return $"{title}\nStep {current}/{total}\n{instruction}";
        }

        private GameObject ResolvePrefab(string visualType)
        {
            if (string.IsNullOrWhiteSpace(visualType))
            {
                return highlightPrefab;
            }

            string normalized = visualType.Trim().ToLowerInvariant();
            return normalized switch
            {
                "arrow" => arrowPrefab,
                "highlight" => highlightPrefab,
                _ => highlightPrefab
            };
        }

        private static GameObject CreateFallback(Vector3 position)
        {
            var fallback = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            fallback.transform.position = position;
            fallback.transform.localScale = Vector3.one * 0.08f;
            var renderer = fallback.GetComponent<Renderer>();
            if (renderer != null)
            {
                renderer.material.color = Color.red;
            }
            return fallback;
        }

        private void ApplyOverlayVisualTuning(GameObject overlay)
        {
            Collider[] colliders = overlay.GetComponentsInChildren<Collider>(true);
            foreach (var collider in colliders)
            {
                collider.enabled = false;
            }

            Renderer[] renderers = overlay.GetComponentsInChildren<Renderer>(true);
            foreach (var renderer in renderers)
            {
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                renderer.receiveShadows = false;

                if (renderer.material != null && renderer.material.HasProperty("_Color"))
                {
                    Color color = renderer.material.color;
                    color.a = overlayOpacity;
                    renderer.material.color = color;
                }
            }
        }

        [Serializable]
        private class GuidanceMessage
        {
            public string type;
            public string task;
            public string instruction_text;
            public string visual_type;
            public float[] location_3d;
            public string response_text;
            public string user_message;
            public StepGuidance step_guidance;
        }

        [Serializable]
        private class StepGuidance
        {
            public string recipe_title;
            public int current_step;
            public int total_steps;
            public StepItem[] steps;
        }

        [Serializable]
        private class StepItem
        {
            public string instruction;
        }
    }
}
