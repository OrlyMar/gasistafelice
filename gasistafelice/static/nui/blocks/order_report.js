
jQuery.UIBlockOrderReport = jQuery.UIBlockWithList.extend({

    init: function() {
        this._super("order_report", "table");
        this.submit_name = "Togli prodotti da gli ordini (elimina prodotti deselezionati da gli ordini dei gasisti)";
    },
        //this.active_view = "edit_multiple";
        //this.default_view = this.active_view;

    rendering_table_post_load_handler: function() {

        var block_obj = this;
        // Init dataTables
        var iTot = 7;
                //'sPaginationType': 'full_numbers',
        var oTable = this.block_el.find('.dataTable').dataTable({
                'bPaginate': false, 
                "bServerSide": true,
                "bStateSave": true,
                "sAjaxSource": this.get_data_source(),
                "aaSorting": [[1,"asc"]],
                "aoColumns": [
                    { "sWidth": "5%", "bSearchable":true},
                    { "sWidth": "50%", "bSearchable":true, "sClass": "left_text"},
                    { "sWidth": "10%", "sType": "currency", "sClass": "taright", "bSearchable" : false},
                    { "sWidth": "5%", "bSortable" : false, "bSearchable" : false},
                    { "sWidth": "5%", "bSortable" : false, "sClass": "taright", "bSearchable" : false},
                    { "sWidth": "5%", "bSortable" : false, "bSearchable" : false},
                    { "sWidth": "5%", "bSortable" : false, "sClass": "taright", "bSearchable" : false},
                    { "sWidth": "10%", "bSortable" : false, "sClass": "taright", "bSearchable" : false},
                    { "sWidth": "5%", "bSearchable" : false}
                ],
                "oLanguage": {
                    "sLengthMenu": gettext("Display _MENU_ records per page"),
                    "sZeroRecords": gettext("Nothing found"),
                    "sInfo": gettext("Showing _START_ to _END_ of _TOTAL_ records"),
                    "sInfoEmpty": gettext("Showing 0 to 0 of 0 records"),
                    "sInfoFiltered": gettext("(filtered from _MAX_ total records)")
                },
                "fnRowCallback": function(nRow, aaData, iDisplayIndex, iDisplayIndexFull) {
                    try {
                        var url = aaData[9];
                        if (url !== undefined) {
                            var _name = aaData[1];
                            res = new jQuery.Resource(url, _name);
                            $(nRow.cells[1]).html( res.render() );
                        }
                    }
                    catch(e){alert(e.message);
                    }
                    return nRow;
                } ,
                "fnFooterCallback": function ( nRow, aaData, iStart, iEnd, aiDisplay ) {

                    var iTotal = 0;
                    var i=0;
                    for ( i=0; i<aaData.length; i++ ) {
                        iTotal += parseFloat(aaData[i][iTot].substr(8).replace(',','.'));
                    }

                    /* Modify the footer row to match what we want */
                    var nCells = $(nRow).find('th');
                    $(nCells[1]).html('&#8364; ' + String(GetRoundedFloat(iTotal)).replace('.',','));

                    /* Modify Django management form info */
                    /* FIXME should not be here this kind of logic computation */
                    $('#' + block_obj.block_box_id + '-form-TOTAL_FORMS').val(iEnd-iStart);
                }
            });


        return this._super();

    }

});

jQuery.BLOCKS.order_report = new jQuery.UIBlockOrderReport();

