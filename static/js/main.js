// Common JavaScript functions
document.addEventListener('DOMContentLoaded', function() {
    // Enable tooltips
    $('[data-toggle="tooltip"]').tooltip();

    // Enable tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });

    // Confirm before delete actions
    $('.confirm-before-delete').on('click', function(e) {
        if (!confirm('Вы уверены, что хотите выполнить это действие?')) {
            e.preventDefault();
        }
    });

    // Auto-hide alerts after 5 seconds
    setTimeout(function() {
        $('.alert').fadeOut('slow');
    }, 5000);

    // Chemical calculation form
    $('#chemical-calculation-form').on('submit', function(e) {
        e.preventDefault();
        const area = parseFloat($('#area-input').val());
        const materialId = $('#material-select').val();
        const ratio = 0.1; // Example ratio - 0.1 liters per m²

        if (area && materialId) {
            const quantity = (area * ratio).toFixed(2);
            $('#quantity-input').val(quantity);
        }
    });

    // Equipment usage timer
    $('.start-timer').on('click', function() {
        const equipmentId = $(this).data('equipment-id');
        const startTime = new Date().getTime();

        localStorage.setItem(`equipment_${equipmentId}_start`, startTime);
        $(this).hide();
        $(`#stop-timer-${equipmentId}`).show();
    });

    $('.stop-timer').on('click', function() {
        const equipmentId = $(this).data('equipment-id');
        const startTime = localStorage.getItem(`equipment_${equipmentId}_start`);

        if (startTime) {
            const endTime = new Date().getTime();
            const minutesUsed = Math.round((endTime - startTime) / 60000);
            $(`#minutes-used-${equipmentId}`).val(minutesUsed);
            localStorage.removeItem(`equipment_${equipmentId}_start`);
            $(this).hide();
            $(`#start-timer-${equipmentId}`).show();
        }
    });
});