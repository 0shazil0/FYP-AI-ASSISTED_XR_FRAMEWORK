using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace NeuroGuideXR.AR
{
    /// <summary>
    /// Renders AR overlays (step-guidance cards, object-highlight markers)
    /// in response to WebSocket guidance messages.
    ///
    /// No debug geometry is ever placed in the AR view.
    /// Hint markers use invisible anchor GameObjects; the visible content
    /// is the world-space Canvas card and the ExerciseGifPanel.
    /// </summary>
    public class AROverlayManager : MonoBehaviour
    {
        // ── Inspector ─────────────────────────────────────────────────────────
        [Header("Prefabs (optional — leave empty for clean AR view)")]
        public GameObject highlightPrefab;
        public GameObject arrowPrefab;

        [Header("Overlay Settings")]
        public float defaultDistance   = 1.5f;
        public float defaultOverlayScale = 0.15f;
        public Vector3 cardLocalOffset = new Vector3(0f, 0.25f, 0f);
        public bool renderStepCard = true;

        [Header("Hint Tracking")]
        public float hintTrackStaleSeconds = 6f;
        public float hintConfidenceThreshold = 0.25f;
        public float hintSmoothingAlpha = 0.35f;
        public float maxHintMovePerUpdate = 0.25f;
        public int   minStableFrames = 2;
        public bool  calibrationMode = false;

        // ── Runtime state ─────────────────────────────────────────────────────
        private GameObject _activeOverlay;
        private GameObject _activeStepCard;

        private readonly Dictionary<string, GameObject>       _hintMarkers   = new();
        private readonly Dictionary<string, TrackedHintState> _trackedHints  = new();

        // ── Data models ───────────────────────────────────────────────────────

        [Serializable]
        public class GuidanceMessage
        {
            public string   task;
            public string   instruction_text;
            public string   visual_type;
            public float[]  location_3d;
            public string[] objects_detected;
            public int      step_number;
            public int      total_steps;
            public string   user_message;
            public StepGuidance step_guidance;
            public DebugInfo debug;
        }

        [Serializable]
        public class StepGuidance
        {
            public string   recipe_title;
            public int      current_step;
            public int      total_steps;
            public bool     is_complete;
            public string[] completed_steps;
            public Step[]   steps;
            public HintRef  active_hint;
        }

        [Serializable]
        public class Step
        {
            public string instruction;
            public string target_object;
        }

        [Serializable]
        public class HintRef
        {
            public string target_object;
        }

        [Serializable]
        public class DebugInfo
        {
            public ObjectHint[] object_hints;
        }

        [Serializable]
        public class ObjectHint
        {
            public string  label;
            public float   confidence;
            public float[] bbox;
        }

        private class HintCandidate
        {
            public string  key;
            public string  label;
            public float   confidence;
            public Vector3 worldPosition;
        }

        private class TrackedHintState
        {
            public string  label;
            public float   confidence;
            public Vector3 worldPosition;
            public int     seenFrames;
            public float   lastSeenAt;
        }

        // ── Public API ────────────────────────────────────────────────────────

        public void Render(GuidanceMessage message)
        {
            if (message == null) return;

            Camera camera = Camera.main;
            if (camera == null) return;

            // Clear previous overlay card (not markers — those are tracked separately)
            ClearActiveOverlay();

            // ── World position ────────────────────────────────────────────────
            Vector3 worldPosition;
            if (message.location_3d != null && message.location_3d.Length == 3)
            {
                worldPosition = camera.transform.position
                    + camera.transform.forward * Mathf.Clamp(message.location_3d[2], 0.8f, 3f)
                    + camera.transform.right   * message.location_3d[0]
                    + camera.transform.up      * (message.location_3d[1] - 1.3f);
            }
            else
            {
                worldPosition = camera.transform.position + camera.transform.forward * defaultDistance;
            }

            // ── Active overlay anchor (invisible — no debug geometry) ─────────
            // If a prefab is assigned, instantiate it; otherwise use invisible fallback.
            // In normal AR Coach operation leave highlightPrefab and arrowPrefab EMPTY
            // in the inspector to keep the AR view clean.
            bool emphasizeStepTarget = false;
            if (message.step_guidance != null)
            {
                string stepTarget = ResolveStepTarget(message);
                emphasizeStepTarget = !string.IsNullOrWhiteSpace(stepTarget);
            }

            GameObject prefab = ResolvePrefab(message.visual_type);
            _activeOverlay = prefab != null
                ? Instantiate(prefab, worldPosition, Quaternion.identity)
                : CreateFallback(worldPosition);

            _activeOverlay.transform.localScale = Vector3.one * defaultOverlayScale;
            // Face the canvas toward the camera (away from camera direction = correct WorldSpace Canvas orientation)
            FaceCamera(_activeOverlay.transform, worldPosition, camera.transform.position);
            _activeOverlay.name = "GuidanceOverlay";
            ApplyOverlayVisualTuning(_activeOverlay, emphasizeStepTarget: false);

            // ── Step guidance card ────────────────────────────────────────────
            if (renderStepCard && message.step_guidance != null)
            {
                Vector3 cardPos = worldPosition + cardLocalOffset;
                _activeStepCard = CreateStepCard(cardPos, camera.transform.position, message);
            }

            RenderObjectHighlights(message, camera.transform);

            Debug.Log($"Guidance overlay rendered at {worldPosition}");
        }

        private void RenderObjectHighlights(GuidanceMessage message, Transform cameraTransform)
        {
            if (message == null || cameraTransform == null) return;

            string stepTarget = ResolveStepTarget(message);
            var candidates    = new List<HintCandidate>();

            if (message.debug?.object_hints != null && message.debug.object_hints.Length > 0)
            {
                int maxHighlights = Mathf.Min(4, message.debug.object_hints.Length);
                for (int index = 0; index < maxHighlights; index++)
                {
                    ObjectHint hint = message.debug.object_hints[index];
                    if (hint == null || hint.bbox == null || hint.bbox.Length != 4) continue;
                    if (hint.confidence < hintConfidenceThreshold) continue;

                    Vector3 position = BboxToWorld(hint.bbox, cameraTransform);
                    string  label    = string.IsNullOrWhiteSpace(hint.label) ? "object" : hint.label.Trim();
                    candidates.Add(new HintCandidate
                    {
                        key           = BuildTrackKey(label, index),
                        label         = label,
                        confidence    = hint.confidence,
                        worldPosition = position,
                    });
                }
            }

            if (candidates.Count == 0 && message.objects_detected != null && message.objects_detected.Length > 0)
            {
                int count = Mathf.Min(4, message.objects_detected.Length);
                for (int index = 0; index < count; index++)
                {
                    string label      = string.IsNullOrWhiteSpace(message.objects_detected[index]) ? "object" : message.objects_detected[index].Trim();
                    float  horizontal = (index - (count - 1) * 0.5f) * 0.12f;
                    Vector3 position  = cameraTransform.position
                        + cameraTransform.forward * defaultDistance
                        + cameraTransform.right   * horizontal;
                    candidates.Add(new HintCandidate
                    {
                        key           = BuildTrackKey(label, index),
                        label         = label,
                        confidence    = 1f,
                        worldPosition = position,
                    });
                }
            }

            UpdateTrackedHints(candidates, cameraTransform, stepTarget);
        }

        private Vector3 BboxToWorld(float[] bbox, Transform cameraTransform)
        {
            float x1 = Mathf.Clamp01(bbox[0]);
            float y1 = Mathf.Clamp01(bbox[1]);
            float x2 = Mathf.Clamp01(bbox[2]);
            float y2 = Mathf.Clamp01(bbox[3]);

            float centerX = (x1 + x2) * 0.5f;
            float centerY = (y1 + y2) * 0.5f;
            float offsetX = (centerX - 0.5f) * 0.8f;
            float offsetY = (0.5f - centerY) * 0.6f;

            return cameraTransform.position
                   + cameraTransform.forward * defaultDistance
                   + cameraTransform.right   * offsetX
                   + cameraTransform.up      * offsetY;
        }

        private void UpdateTrackedHints(List<HintCandidate> candidates, Transform cameraTransform, string stepTarget)
        {
            var seenKeys = new HashSet<string>();

            foreach (HintCandidate candidate in candidates)
            {
                seenKeys.Add(candidate.key);

                if (!_trackedHints.TryGetValue(candidate.key, out TrackedHintState state))
                {
                    state = new TrackedHintState
                    {
                        label         = candidate.label,
                        worldPosition = candidate.worldPosition,
                        confidence    = Mathf.Clamp01(candidate.confidence),
                        seenFrames    = 1,
                        lastSeenAt    = Time.time,
                    };
                }
                else
                {
                    state.label         = candidate.label;
                    state.confidence    = Mathf.Lerp(state.confidence, Mathf.Clamp01(candidate.confidence), calibrationMode ? hintSmoothingAlpha : 1f);
                    state.worldPosition = SmoothPosition(state.worldPosition, candidate.worldPosition);
                    state.seenFrames   += 1;
                    state.lastSeenAt    = Time.time;
                }

                _trackedHints[candidate.key] = state;

                bool isStable = !calibrationMode || state.seenFrames >= minStableFrames;
                if (!isStable) continue;

                // Always use invisible fallback markers — no geometry in AR view
                GameObject marker = GetOrCreateHintMarker(candidate.key, state.worldPosition, state.label);
                bool emphasize    = IsStepTarget(state.label, stepTarget);
                UpdateHintMarker(marker, state.worldPosition, cameraTransform, emphasize);
            }

            PruneStaleTrackedHints(seenKeys);
        }

        private GameObject GetOrCreateHintMarker(string key, Vector3 position, string label)
        {
            if (_hintMarkers.TryGetValue(key, out GameObject existing) && existing != null)
            {
                return existing;
            }

            // Always use invisible fallback — no geometry placed in AR view.
            // highlightPrefab / arrowPrefab are reserved for future prefab-based
            // markers but should be left EMPTY in the inspector for AR Coach mode.
            GameObject marker = CreateFallback(position);
            marker.name = string.IsNullOrWhiteSpace(label) ? "ObjectHighlight" : $"ObjectHighlight_{label}";
            _hintMarkers[key] = marker;
            return marker;
        }

        private void UpdateHintMarker(GameObject marker, Vector3 position, Transform cameraTransform, bool emphasizeStepTarget)
        {
            if (marker == null || cameraTransform == null) return;

            marker.SetActive(true);
            marker.transform.position   = position;
            marker.transform.localScale = Vector3.one * (defaultOverlayScale * (emphasizeStepTarget ? 1.05f : 0.7f));
            FaceCamera(marker.transform, position, cameraTransform.position);
            ApplyOverlayVisualTuning(marker, emphasizeStepTarget);
        }

        private void PruneStaleTrackedHints(HashSet<string> seenKeys)
        {
            float now     = Time.time;
            var staleKeys = new List<string>();
            foreach (var item in _trackedHints)
            {
                if (!seenKeys.Contains(item.Key) && now - item.Value.lastSeenAt > hintTrackStaleSeconds)
                {
                    staleKeys.Add(item.Key);
                }
            }

            foreach (string key in staleKeys)
            {
                _trackedHints.Remove(key);
                if (_hintMarkers.TryGetValue(key, out GameObject marker) && marker != null)
                {
                    Destroy(marker);
                }
                _hintMarkers.Remove(key);
            }
        }

        private Vector3 SmoothPosition(Vector3 previous, Vector3 incoming)
        {
            if (!calibrationMode) return incoming;

            Vector3 smoothed  = Vector3.Lerp(previous, incoming, hintSmoothingAlpha);
            if (maxHintMovePerUpdate <= 0f) return smoothed;

            Vector3 delta     = smoothed - previous;
            float   magnitude = delta.magnitude;
            if (magnitude <= maxHintMovePerUpdate || magnitude <= Mathf.Epsilon) return smoothed;

            return previous + delta.normalized * maxHintMovePerUpdate;
        }

        private static string BuildTrackKey(string label, int index) =>
            $"{label.Trim().ToLowerInvariant()}#{index}";

        private static bool IsStepTarget(string label, string stepTarget)
        {
            if (string.IsNullOrWhiteSpace(label) || string.IsNullOrWhiteSpace(stepTarget)) return false;

            string nl = label.Trim().ToLowerInvariant();
            string nt = stepTarget.Trim().ToLowerInvariant();
            if (nt == "scene" || nt == "object") return false;

            return nl.Contains(nt) || nt.Contains(nl);
        }

        private static string ResolveStepTarget(GuidanceMessage message)
            => message?.step_guidance?.active_hint?.target_object ?? string.Empty;

        private void ClearTrackedHints()
        {
            foreach (var marker in _hintMarkers.Values)
            {
                if (marker != null) Destroy(marker);
            }
            _hintMarkers.Clear();
            _trackedHints.Clear();
        }

        // ── Step Card ─────────────────────────────────────────────────────────

        private GameObject CreateStepCard(Vector3 worldPosition, Vector3 cameraPosition, GuidanceMessage message)
        {
            // ── World-space Canvas (crisp, anti-aliased text; no raw geometry) ─
            var cardRoot = new GameObject("StepGuidanceCard");
            cardRoot.transform.position = worldPosition;

            // FIX: Use LookRotation(away-from-camera) not LookAt(camera).
            // WorldSpace Canvas is visible from the +Z side. To face the camera,
            // the canvas's +Z must point AWAY from the camera (toward the user).
            BillboardFaceCamera(cardRoot.transform, worldPosition, cameraPosition);

            // Canvas
            var canvas = cardRoot.AddComponent<Canvas>();
            canvas.renderMode  = RenderMode.WorldSpace;
            canvas.worldCamera = Camera.main;
            cardRoot.AddComponent<GraphicRaycaster>();

            // Scale: 1 px = 0.001 m → card 480×200 px = 0.48×0.20 m
            cardRoot.transform.localScale = Vector3.one * 0.001f;

            var canvasRt      = canvas.GetComponent<RectTransform>();
            canvasRt.sizeDelta = new Vector2(480f, 200f);

            // Background panel
            var bg   = new GameObject("BG", typeof(RectTransform), typeof(Image));
            bg.transform.SetParent(canvasRt, false);
            var bgRt = bg.GetComponent<RectTransform>();
            bgRt.anchorMin = Vector2.zero;
            bgRt.anchorMax = Vector2.one;
            bgRt.sizeDelta = Vector2.zero;
            bg.GetComponent<Image>().color = new Color(0.05f, 0.09f, 0.16f, 0.93f);

            // Accent bar (top edge)
            var accentGo = new GameObject("Accent", typeof(RectTransform), typeof(Image));
            accentGo.transform.SetParent(canvasRt, false);
            var acRt  = accentGo.GetComponent<RectTransform>();
            acRt.anchorMin = new Vector2(0f, 1f);
            acRt.anchorMax = new Vector2(1f, 1f);
            acRt.pivot     = new Vector2(0.5f, 1f);
            acRt.sizeDelta = new Vector2(0f, 5f);
            accentGo.GetComponent<Image>().color = new Color(0.18f, 0.56f, 1f, 1f);

            // Text
            var font   = Resources.GetBuiltinResource<Font>("Arial.ttf");
            var textGo = new GameObject("Text", typeof(RectTransform), typeof(Text));
            textGo.transform.SetParent(canvasRt, false);
            var textRt = textGo.GetComponent<RectTransform>();
            textRt.anchorMin        = Vector2.zero;
            textRt.anchorMax        = Vector2.one;
            textRt.sizeDelta        = new Vector2(-24f, -20f);
            textRt.anchoredPosition = Vector2.zero;
            var txt    = textGo.GetComponent<Text>();
            txt.font               = font;
            txt.fontSize           = 28;
            txt.fontStyle          = FontStyle.Normal;
            txt.color              = new Color(0.93f, 0.97f, 1f, 1f);
            txt.alignment          = TextAnchor.MiddleCenter;
            txt.horizontalOverflow = HorizontalWrapMode.Wrap;
            txt.verticalOverflow   = VerticalWrapMode.Overflow;
            txt.supportRichText    = true;
            txt.text               = BuildCardText(message);

            return cardRoot;
        }

        /// <summary>
        /// Orients a Transform so its world-space Canvas or mesh faces the camera.
        /// For WorldSpace Canvas: +Z must point AWAY from the camera (toward the viewer).
        /// </summary>
        private static void BillboardFaceCamera(Transform t, Vector3 objectPos, Vector3 cameraPos)
        {
            // Direction from camera to this object — canvas's +Z should point along this.
            Vector3 forward = (objectPos - cameraPos).normalized;

            // Gimbal-lock guard: if the card is almost directly above/below camera,
            // use Vector3.forward as the up axis to prevent flipping.
            Vector3 up = Mathf.Abs(Vector3.Dot(forward, Vector3.up)) > 0.98f
                ? Vector3.forward
                : Vector3.up;

            t.rotation = Quaternion.LookRotation(forward, up);
        }

        /// <summary>
        /// Orients any non-canvas object (meshes, prefabs) to face the camera.
        /// These use +Z toward the camera (opposite of BillboardFaceCamera).
        /// </summary>
        private static void FaceCamera(Transform t, Vector3 objectPos, Vector3 cameraPos)
        {
            Vector3 forward = (cameraPos - objectPos).normalized;
            Vector3 up      = Mathf.Abs(Vector3.Dot(forward, Vector3.up)) > 0.98f
                ? Vector3.forward
                : Vector3.up;
            t.rotation = Quaternion.LookRotation(forward, up);
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

            int  current        = Mathf.Max(1, message.step_guidance.current_step);
            int  total          = Mathf.Max(current, message.step_guidance.total_steps);
            int  completedCount = message.step_guidance.completed_steps?.Length ?? 0;
            bool isComplete     = message.step_guidance.is_complete || completedCount >= total;

            string instruction = message.instruction_text;
            if (message.step_guidance.steps != null && message.step_guidance.steps.Length >= current && !isComplete)
            {
                var step = message.step_guidance.steps[current - 1];
                if (!string.IsNullOrWhiteSpace(step.instruction))
                    instruction = step.instruction;
            }

            if (string.IsNullOrWhiteSpace(instruction))
                instruction = "Follow the highlighted step.";

            string targetObject    = message.step_guidance.active_hint?.target_object ?? string.Empty;
            bool   hasTargetObject = !string.IsNullOrWhiteSpace(targetObject)
                && !string.Equals(targetObject.Trim(), "scene",  StringComparison.OrdinalIgnoreCase)
                && !string.Equals(targetObject.Trim(), "object", StringComparison.OrdinalIgnoreCase);

            if (isComplete)
                return $"{title}\nCompleted {completedCount}/{total}\nAll steps completed.";

            if (hasTargetObject)
                return $"{title}\nStep {current}/{total} | Done {completedCount}/{total}\nTarget: {targetObject.Trim()}\n{instruction}";

            return $"{title}\nStep {current}/{total} | Done {completedCount}/{total}\n{instruction}";
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private GameObject ResolvePrefab(string visualType)
        {
            if (string.IsNullOrWhiteSpace(visualType)) return highlightPrefab;

            return visualType.Trim().ToLowerInvariant() switch
            {
                "arrow"     => arrowPrefab,
                "highlight" => highlightPrefab,
                _           => highlightPrefab,
            };
        }

        /// <summary>Returns a lightweight invisible anchor — no geometry in AR view.</summary>
        private static GameObject CreateFallback(Vector3 position)
        {
            var fallback = new GameObject("OverlayAnchor");
            fallback.transform.position = position;
            return fallback;
        }

        private void ClearActiveOverlay()
        {
            if (_activeOverlay != null)
            {
                Destroy(_activeOverlay);
                _activeOverlay = null;
            }

            if (_activeStepCard != null)
            {
                Destroy(_activeStepCard);
                _activeStepCard = null;
            }
        }

        private void ApplyOverlayVisualTuning(GameObject overlay, bool emphasizeStepTarget)
        {
            if (overlay == null) return;

            var renderers = overlay.GetComponentsInChildren<Renderer>(true);
            foreach (var r in renderers)
            {
                // Invisible fallback anchors have no renderer — skip
                var mat = r.material;
                if (mat == null) continue;

                Color tint = emphasizeStepTarget
                    ? new Color(0.18f, 0.7f, 1f, 0.85f)
                    : new Color(0.25f, 0.55f, 1f, 0.6f);

                if (mat.HasProperty("_Color"))   mat.color = tint;
                if (mat.HasProperty("_TintColor")) mat.SetColor("_TintColor", tint);
            }
        }

        private static bool ShouldRenderMessage(string msgType)
        {
            return msgType == "guidance"
                || msgType == "snapshot_result"
                || msgType == "prompt_response"
                || msgType == "step_update";
        }
    }
}
