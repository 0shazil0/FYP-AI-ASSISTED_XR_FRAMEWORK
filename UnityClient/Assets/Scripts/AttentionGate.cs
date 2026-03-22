using UnityEngine;

[RequireComponent(typeof(ARCameraCapture))]
public class AttentionGate : MonoBehaviour
{
    [Header("Attention Thresholds")]
    [Tooltip("Maximum allowed acceleration magnitude for fixation")]
    public float accelThreshold = 0.5f; 
    
    [Tooltip("Maximum allowed angular velocity magnitude for fixation")]
    public float gyroThreshold = 0.5f; 
    
    [Tooltip("Time in seconds the user must hold still to trigger capture")]
    public float fixationTimeRequired = 1.0f;

    [Tooltip("Cooldown period between captures in seconds")]
    public float cooldownTime = 2.0f;

    private ARCameraCapture _cameraCapture;
    private float _fixationTimer = 0f;
    private float _cooldownTimer = 0f;

    private void Awake()
    {
        _cameraCapture = GetComponent<ARCameraCapture>();
        Input.gyro.enabled = true;
    }

    private void Update()
    {
        if (_cooldownTimer > 0)
        {
            _cooldownTimer -= Time.deltaTime;
            return;
        }

        Vector3 acceleration = Input.acceleration;
        Vector3 gyro = Input.gyro.rotationRateUnbiased;

        // Check if device is stable (below thresholds)
        if (acceleration.magnitude < accelThreshold && gyro.magnitude < gyroThreshold)
        {
            _fixationTimer += Time.deltaTime;
            
            if (_fixationTimer >= fixationTimeRequired)
            {
                TriggerCapture();
                _fixationTimer = 0f;
                _cooldownTimer = cooldownTime;
            }
        }
        else
        {
            // Reset timer if device moves too much
            _fixationTimer = 0f;
        }
    }

    private void TriggerCapture()
    {
        Debug.Log("Attention Gate: Fixation detected. Capturing frame.");
        StartCoroutine(_cameraCapture.CaptureAndSendFrame());
    }
}
