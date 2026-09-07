// Assets/Scripts/Copilot/CopilotOverlayManager.cs
// Maps pywinauto / OmniParser pixel coords → AR virtual screen Quad positions.
// Places animated arrow + pulsing ring highlight + step counter badge at each step.

using System.Collections;
using System.Collections.Generic;
using TMPro;
using UnityEngine;

namespace NeuroGuideXR.Copilot
{
    public sealed class CopilotOverlayManager : MonoBehaviour
    {
        // ----------------------------------------------------------------
        // Inspector
        // ----------------------------------------------------------------
        [Header("Virtual Screen Reference")]
        [Tooltip("Transform of the AR Quad (VirtualScreen GameObject).")]
        [SerializeField] private Transform virtualScreen;

        [Tooltip("Width of the Quad in Unity units (match Quad scale X). Default 16 for 16:9.")]
        [SerializeField] private float planeWidth = 16f;

        [Tooltip("Height of the Quad in Unity units (match Quad scale Y). Default 9 for 16:9.")]
        [SerializeField] private float planeHeight = 9f;

        [Header("Prefabs (optional — fallbacks used if null)")]
        [Tooltip("Arrow prefab instantiated at the target button.")]
        [SerializeField] private GameObject arrowPrefab;

        [Tooltip("Label prefab with TextMeshPro component.")]
        [SerializeField] private GameObject labelPrefab;

        [Header("Animation")]
        [SerializeField] private float bounceAmplitude = 0.10f;
        [SerializeField] private float bounceFrequency = 2.2f;

        [Header("Ring Highlight")]
        [Tooltip("Colour of the pulsing ring around the target element.")]
        [SerializeField] private Color ringColor = new Color(0.25f, 0.85f, 1.0f, 0.85f);
        [Tooltip("Base scale of the ring in Unity units.")]
        [SerializeField] private float ringBaseScale = 0.55f;
        [Tooltip("Pulse amplitude (ring expands by this each cycle).")]
        [SerializeField] private float ringPulseAmp  = 0.12f;
        [SerializeField] private float ringPulseFreq = 1.8f;

        [Header("Step Counter Badge")]
        [SerializeField] private Color badgeColor = new Color(0.12f, 0.52f, 0.96f);

        // ----------------------------------------------------------------
        // Runtime
        // ----------------------------------------------------------------
        private GameObject          _currentArrow;
        private GameObject          _currentLabel;
        private GameObject          _currentRing;
        private GameObject          _currentBadge;
        private Coroutine           _bounceRoutine;
        private Coroutine           _ringRoutine;
        private readonly List<GameObject> _allOverlays = new();

        // ----------------------------------------------------------------
        // Public API
        // ----------------------------------------------------------------

        /// <summary>
        /// Place an animated arrow + highlight ring + step badge at the given
        /// pixel coordinates relative to the reference screen resolution.
        ///
        /// Coordinate mapping:
        ///   Unity X = (screenX / screenW − 0.5) × planeWidth
        ///   Unity Y = −(screenY / screenH − 0.5) × planeHeight   ← Y flipped!
        /// </summary>
        public void PlaceOverlay(
            float screenX, float screenY,
            float screenW, float screenH,
            string labelText,
            int stepIndex = 0,
            int totalSteps = 0)
        {
            if (virtualScreen == null)
            {
                Debug.LogWarning("[CopilotOverlay] virtualScreen not assigned.");
                return;
            }

            // ── Normalise & map to Quad local space (compensating for parent scale) ──────────────────────
            float nx = Mathf.Clamp01(screenX / screenW);
            float ny = Mathf.Clamp01(screenY / screenH);
            float localX = nx - 0.5f;
            float localY = -(ny - 0.5f);
            Vector3 localPos = new(localX, localY, -0.025f);

            // Clear previous step's overlays
            ClearCurrentOverlay();

            // ── Arrow ─────────────────────────────────────────────────────
            if (arrowPrefab != null)
            {
                _currentArrow = Instantiate(arrowPrefab, virtualScreen);
                _currentArrow.transform.localPosition = localPos;
                _currentArrow.transform.localRotation = Quaternion.identity;
                _currentArrow.name = "CopilotArrow";
            }
            else
            {
                _currentArrow = CreateFallbackArrow(localPos, virtualScreen);
            }

            if (_bounceRoutine != null) StopCoroutine(_bounceRoutine);
            if (_currentArrow != null)
                _bounceRoutine = StartCoroutine(BounceRoutine(_currentArrow, localPos));

            // ── Pulsing ring highlight ────────────────────────────────────
            _currentRing = CreateRing(localPos, virtualScreen);
            if (_ringRoutine != null) StopCoroutine(_ringRoutine);
            if (_currentRing != null)
                _ringRoutine = StartCoroutine(PulseRingRoutine(_currentRing));

            // ── Label ──────────────────────────────────────────────────────
            if (!string.IsNullOrEmpty(labelText))
            {
                if (labelPrefab != null)
                {
                    _currentLabel = Instantiate(labelPrefab, virtualScreen);
                    var tmp = _currentLabel.GetComponentInChildren<TextMeshPro>();
                    if (tmp != null) tmp.text = labelText;
                    _currentLabel.transform.localPosition = localPos + new Vector3(0f, 0.70f / planeHeight, -0.01f);
                    _currentLabel.transform.localRotation = Quaternion.identity;
                }
                else
                {
                    _currentLabel = CreateFallbackLabel(labelText, localPos, virtualScreen);
                }
                _currentLabel.name = "CopilotLabel";
            }

            // ── Step counter badge (e.g. "2 / 5") ────────────────────────
            if (totalSteps > 0)
            {
                _currentBadge = CreateStepBadge(stepIndex, totalSteps, localPos, virtualScreen);
            }

            Debug.Log($"[CopilotOverlay] Step {stepIndex + 1}/{totalSteps} → " +
                      $"local ({localX:F2}, {localY:F2}) for '{labelText}'");
        }

        /// <summary>Clear only the current step's active overlays.</summary>
        public void ClearCurrentOverlay()
        {
            if (_bounceRoutine != null) { StopCoroutine(_bounceRoutine); _bounceRoutine = null; }
            if (_ringRoutine   != null) { StopCoroutine(_ringRoutine);   _ringRoutine   = null; }
            SafeDestroy(ref _currentArrow);
            SafeDestroy(ref _currentLabel);
            SafeDestroy(ref _currentRing);
            SafeDestroy(ref _currentBadge);
        }

        /// <summary>Clear ALL overlays spawned by this manager.</summary>
        public void ClearAll()
        {
            ClearCurrentOverlay();
            foreach (var go in _allOverlays)
                if (go != null) Destroy(go);
            _allOverlays.Clear();
        }

        // ----------------------------------------------------------------
        // Animation coroutines
        // ----------------------------------------------------------------

        private IEnumerator BounceRoutine(GameObject obj, Vector3 baseLocalPos)
        {
            float t = 0f;
            while (obj != null)
            {
                t += Time.deltaTime * bounceFrequency;
                // Bounce vertically relative to the plane height
                obj.transform.localPosition =
                    baseLocalPos + new Vector3(0f, Mathf.Sin(t) * bounceAmplitude / planeHeight, 0f);
                yield return null;
            }
        }

        private IEnumerator PulseRingRoutine(GameObject ring)
        {
            float t = 0f;
            while (ring != null)
            {
                t += Time.deltaTime * ringPulseFreq;
                float scaleMultiplier = 1.0f + Mathf.Abs(Mathf.Sin(t)) * (ringPulseAmp / ringBaseScale);
                float scaleX = (ringBaseScale / planeWidth) * scaleMultiplier;
                float scaleY = (ringBaseScale / planeHeight) * scaleMultiplier;
                ring.transform.localScale = new Vector3(scaleX, 0.002f, scaleY);

                // Also pulse alpha
                var r = ring.GetComponent<Renderer>();
                if (r != null && r.material != null)
                {
                    Color c = ringColor;
                    c.a = 0.45f + 0.4f * Mathf.Abs(Mathf.Sin(t));
                    r.material.color = c;
                }
                yield return null;
            }
        }

        // ----------------------------------------------------------------
        // Fallback primitive factories
        // ----------------------------------------------------------------

        private GameObject CreateFallbackArrow(Vector3 localPos, Transform parent)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPos + new Vector3(0f, 0.35f / planeHeight, -0.005f);
            go.transform.localScale    = new Vector3(0.20f / planeWidth, 0.20f / planeHeight, 0.20f);
            go.name = "CopilotArrow_Fallback";
            var rend = go.GetComponent<Renderer>();
            if (rend)
            {
                var screenRend = parent.GetComponent<Renderer>();
                if (screenRend != null) rend.material = new Material(screenRend.sharedMaterial.shader);
                rend.material.color = new Color(1f, 0.45f, 0.1f);
            }
            var col = go.GetComponent<Collider>();
            if (col) col.enabled = false;
            return go;
        }

        private GameObject CreateRing(Vector3 localPos, Transform parent)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPos + new Vector3(0f, 0f, -0.005f);
            go.transform.localRotation = Quaternion.Euler(90f, 0f, 0f); // lay flat on Quad
            go.transform.localScale    = new Vector3(ringBaseScale / planeWidth, 0.002f, ringBaseScale / planeHeight);
            go.name = "CopilotRing";
            var rend = go.GetComponent<Renderer>();
            if (rend)
            {
                var screenRend = parent.GetComponent<Renderer>();
                if (screenRend != null) rend.material = new Material(screenRend.sharedMaterial.shader);
                rend.material.color = ringColor;
            }
            var col = go.GetComponent<Collider>();
            if (col) col.enabled = false;
            return go;
        }

        private GameObject CreateFallbackLabel(string text, Vector3 localPos, Transform parent)
        {
            var go = new GameObject("CopilotLabel_Fallback");
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPos + new Vector3(0f, 0.70f / planeHeight, -0.01f);
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale    = new Vector3(1f / planeWidth, 1f / planeHeight, 1f);

            // TextMeshPro (world-space)
            var tmp = go.AddComponent<TextMeshPro>();
            tmp.text       = text;
            tmp.fontSize   = 3.5f;
            tmp.color      = Color.white;
            tmp.alignment  = TextAlignmentOptions.Center;
            tmp.enableWordWrapping = false;
            return go;
        }

        private GameObject CreateStepBadge(int stepIndex, int totalSteps,
                                           Vector3 localPos, Transform parent)
        {
            var go = new GameObject("CopilotStepBadge");
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPos + new Vector3(-0.45f / planeWidth, 0.55f / planeHeight, -0.015f);
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale    = new Vector3(1f / planeWidth, 1f / planeHeight, 1f);

            var tmp = go.AddComponent<TextMeshPro>();
            tmp.text     = $"{stepIndex + 1} / {totalSteps}";
            tmp.fontSize = 2.8f;
            tmp.color    = badgeColor;
            tmp.fontStyle = FontStyles.Bold;
            tmp.alignment = TextAlignmentOptions.Left;
            return go;
        }

        // ----------------------------------------------------------------
        // Helpers
        // ----------------------------------------------------------------
        private static void SafeDestroy(ref GameObject go)
        {
            if (go != null) { Destroy(go); go = null; }
        }
    }
}
