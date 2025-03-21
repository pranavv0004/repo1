document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Auto-dismiss alerts after 5 seconds
    setTimeout(function() {
        var alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
        alerts.forEach(function(alert) {
            var bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);

    // Group member selection in expense creation
    const groupSelect = document.getElementById('group_id');
    if (groupSelect) {
        groupSelect.addEventListener('change', function() {
            if (this.value) {
                // In a real implementation, this would be an AJAX call to get members
                // For now, we'll handle this in the Flask route
                console.log('Group selected:', this.value);
            }
        });
    }

    // Split method handling in expense creation/editing
    const splitMethodRadios = document.querySelectorAll('input[name="split_method"]');
    if (splitMethodRadios.length > 0) {
        splitMethodRadios.forEach(function(radio) {
            radio.addEventListener('change', function() {
                const splitMethod = this.value;
                const equalSplitSection = document.getElementById('equalSplitSection');
                const unequalSplitSection = document.getElementById('unequalSplitSection');
                
                if (splitMethod === 'equal') {
                    if (equalSplitSection) equalSplitSection.classList.remove('d-none');
                    if (unequalSplitSection) unequalSplitSection.classList.add('d-none');
                } else if (splitMethod === 'unequal') {
                    if (equalSplitSection) equalSplitSection.classList.add('d-none');
                    if (unequalSplitSection) unequalSplitSection.classList.remove('d-none');
                }
            });
        });
    }

    // Calculate total in unequal split
    const amountInputs = document.querySelectorAll('.split-amount-input');
    if (amountInputs.length > 0) {
        amountInputs.forEach(function(input) {
            input.addEventListener('input', calculateTotal);
        });
    }

    function calculateTotal() {
        const totalElement = document.getElementById('splitTotal');
        if (!totalElement) return;
        
        let total = 0;
        document.querySelectorAll('.split-amount-input').forEach(function(input) {
            const value = parseFloat(input.value) || 0;
            total += value;
        });
        
        totalElement.textContent = total.toFixed(2);
        
        // Check if total matches expense amount
        const expenseAmount = parseFloat(document.getElementById('amount').value) || 0;
        if (Math.abs(total - expenseAmount) < 0.01) {
            totalElement.classList.remove('text-danger');
            totalElement.classList.add('text-success');
        } else {
            totalElement.classList.remove('text-success');
            totalElement.classList.add('text-danger');
        }
    }

    // Handle participant checkboxes in expense creation
    const participantCheckboxes = document.querySelectorAll('.participant-checkbox');
    if (participantCheckboxes.length > 0) {
        participantCheckboxes.forEach(function(checkbox) {
            checkbox.addEventListener('change', function() {
                const amountInput = this.closest('.form-check').querySelector('.unequal-amount');
                if (amountInput) {
                    if (this.checked) {
                        amountInput.classList.remove('d-none');
                    } else {
                        amountInput.classList.add('d-none');
                        amountInput.querySelector('input').value = '0';
                        calculateTotal();
                    }
                }
            });
        });
    }
});
